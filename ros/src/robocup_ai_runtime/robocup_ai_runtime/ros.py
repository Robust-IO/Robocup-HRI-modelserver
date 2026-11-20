"""ROS adapters. All long operations run on owned workers, never subscription threads."""
from collections import deque
import threading
import time
import uuid

import rclpy
from rclpy.action import ActionServer, ActionClient, GoalResponse, CancelResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from rclpy.task import Future
from rcl_interfaces.msg import ParameterDescriptor, IntegerRange, FloatingPointRange
from robocup_interfaces.msg import AiServiceStatus
from robocup_interfaces.srv import GetAiServiceStatus
from .core import AiError, Code, Operation, PROTOCOL_VERSION, PACKAGE_VERSION, RequestLedger, validate_protocol


class AiNode(Node):
    def __init__(self, name, service, **kwargs):
        super().__init__(name, **kwargs)
        self.service = service
        self.group = ReentrantCallbackGroup()
        self._qos_cache = {}
        self.stopping = threading.Event()
        self.robot_namespace = self.param('robot_namespace', '/robot1', 'Robot ROS namespace')
        self.protocol = self.param('protocol_version', PROTOCOL_VERSION, 'Deployed protocol version')
        self.release = self.param('release_id', 'development', 'Same Git tag on both roles')
        self.commit = self.param('git_commit', 'unknown', 'Deployment Git commit')
        self.status_lock = threading.RLock()
        self.ready, self.state, self.message = False, 'initializing', 'initializing'
        self.backend_name, self.model = 'none', ''
        self.status_pub = self.create_publisher(AiServiceStatus, self.topic('ai/status'), self.qos('status', 20, transient=True))
        self.status_srv = self.create_service(GetAiServiceStatus, self.topic(f'ai/{service}/status'), self._status, callback_group=self.group)
        self.status_timer = self.create_timer(0.5, self.publish_status)

    def param(self, name, default, description='', minimum=None, maximum=None):
        descriptor = ParameterDescriptor(description=description or name, read_only=True)
        if minimum is not None:
            if isinstance(default, int) and not isinstance(default, bool):
                descriptor.integer_range = [IntegerRange(from_value=int(minimum), to_value=int(maximum), step=1)]
            else:
                descriptor.floating_point_range = [FloatingPointRange(from_value=float(minimum), to_value=float(maximum), step=0.0)]
        return self.declare_parameter(name, default, descriptor).value

    def topic(self, name):
        if name.startswith('/'):
            raise ValueError('endpoint must be relative to robot_namespace')
        return '/' + '/'.join(x.strip('/') for x in (self.robot_namespace, name) if x.strip('/'))

    def qos(self, name, depth, reliable=True, transient=False):
        if name in self._qos_cache:
            return self._qos_cache[name]
        depth = self.param(f'qos.{name}.depth', depth, minimum=1, maximum=1024)
        reliability = self.param(f'qos.{name}.reliability', 'reliable' if reliable else 'best_effort')
        durability = self.param(f'qos.{name}.transient_local', transient)
        if reliability not in ('reliable', 'best_effort'):
            raise ValueError('QoS reliability must be reliable or best_effort')
        if name.startswith('action_') and reliability != 'reliable':
            raise ValueError('Actions require reliable QoS')
        profile = QoSProfile(depth=depth, reliability=ReliabilityPolicy.RELIABLE if reliability == 'reliable' else ReliabilityPolicy.BEST_EFFORT,
                          durability=DurabilityPolicy.TRANSIENT_LOCAL if durability else DurabilityPolicy.VOLATILE)
        self._qos_cache[name] = profile
        return profile

    def snapshot(self):
        with self.status_lock:
            return AiServiceStatus(service_name=self.service, node_name=self.get_fully_qualified_name(),
                                   state=self.state, ready=self.ready, package_version=PACKAGE_VERSION,
                                   protocol_version=self.protocol, release_id=self.release, git_commit=self.commit,
                                   backend=self.backend_name, model=self.model, message=self.message)

    def set_status(self, state, ready, message):
        with self.status_lock:
            changed = (self.state, self.ready, self.message) != (state, ready, message)
            self.state, self.ready, self.message = state, ready, message
        if changed:
            if ready:
                self.get_logger().info(f'{self.service}: {state}: {message}')
            else:
                self.get_logger().warning(f'{self.service}: {state}: {message}')
        self.publish_status()

    def publish_status(self):
        if self.context.ok():
            self.status_pub.publish(self.snapshot())

    def _status(self, request, response):
        response.status = self.snapshot()
        return response

    def stop(self):
        self.stopping.set()


class QueuedServer:
    """One dedicated worker, bounded admission, coroutine callbacks free the executor."""
    def __init__(self, node, action_type, endpoint, handler, capacity=4, timeout=60.0, accepted=None, preempt=False, ready_check=None):
        self.node, self.action_type, self.handler = node, action_type, handler
        self.capacity, self.timeout, self.accepted, self.preempt = capacity, timeout, accepted, preempt
        self.ready_check = ready_check or (lambda: node.ready)
        self.lock = threading.RLock()
        self.wake = threading.Condition(self.lock)
        self.pending = deque()
        self.slots = 0
        self.futures = {}
        self.active = None
        self.interrupted = set()
        self.ledger = RequestLedger()
        self.server = ActionServer(node, action_type, node.topic(endpoint), self.execute,
                                   goal_callback=self.goal, cancel_callback=lambda _: CancelResponse.ACCEPT,
                                   handle_accepted_callback=self.on_accepted, callback_group=node.group,
                                   goal_service_qos_profile=node.qos('action_control', 10),
                                   result_service_qos_profile=node.qos('action_control', 10),
                                   cancel_service_qos_profile=node.qos('action_control', 10),
                                   feedback_pub_qos_profile=node.qos('action_feedback', 10),
                                   status_pub_qos_profile=node.qos('action_status', 10, transient=True),
                                   result_timeout=60)
        self.worker = threading.Thread(target=self.run, name=endpoint, daemon=True)
        self.worker.start()

    def goal(self, request):
        with self.lock:
            if self.node.stopping.is_set() or not self.ready_check() or self.slots >= self.capacity:
                self.node.get_logger().warning('goal rejected: unavailable or queue full; query status service')
                return GoalResponse.REJECT
            try:
                self.ledger.admit(request.request_id)
            except AiError as exc:
                self.node.get_logger().warning(f'goal rejected [{exc.code}]: {exc}')
                return GoalResponse.REJECT
            self.slots += 1
            return GoalResponse.ACCEPT

    def on_accepted(self, handle):
        key = bytes(handle.goal_id.uuid)
        with self.wake:
            future = Future()
            self.futures[key] = future
            try:
                if self.accepted:
                    self.accepted(handle)
                compatible = handle.request.protocol_version == self.node.protocol == PROTOCOL_VERSION
                if compatible and self.preempt and getattr(handle.request, 'interrupt_current', False) and self.active is not None:
                    if handle.request.priority > self.active.request.priority:
                        self.interrupted.add(bytes(self.active.goal_id.uuid))
                        self.pending.appendleft(handle)
                    else:
                        self.pending.append(handle)
                else:
                    self.pending.append(handle)
            except Exception as exc:
                handle.abort()
                result = self.action_type.Result(success=False, error_code=int(Code.INVALID), error_message=str(exc))
                future.set_result(result)
                self.slots -= 1
                self.ledger.finish(handle.request.request_id)
            handle.execute()
            self.wake.notify_all()

    async def execute(self, handle):
        key = bytes(handle.goal_id.uuid)
        result = await self.futures[key]
        with self.lock:
            self.futures.pop(key, None)
        return result

    def run(self):
        while True:
            with self.wake:
                self.wake.wait_for(lambda: self.pending or self.node.stopping.is_set(), timeout=0.1)
                if not self.pending:
                    if self.node.stopping.is_set():
                        return
                    continue
                handle = self.pending.popleft()
                self.active = handle
            key = bytes(handle.goal_id.uuid)
            canceled = lambda: handle.is_cancel_requested or self.node.stopping.is_set() or key in self.interrupted
            op = Operation(self.timeout, canceled)
            try:
                op.check()
                validate_protocol(self.node.protocol)
                validate_protocol(handle.request.protocol_version)
                result = self.handler(handle, op)
                op.check()
                if not result.success:
                    raise AiError(result.error_code, result.error_message)
                handle.succeed()
            except Exception as exc:
                code = exc.code if isinstance(exc, AiError) else int(Code.BACKEND)
                result = self.action_type.Result(success=False, error_code=code, error_message=str(exc))
                if handle.is_cancel_requested:
                    handle.canceled()
                else:
                    handle.abort()
                self.node.get_logger().warning(f'request_id={handle.request.request_id} failed [{code}]: {exc}')
            finally:
                with self.lock:
                    self.active = None
                    self.interrupted.discard(key)
                    self.slots -= 1
                    self.ledger.finish(handle.request.request_id)
            self.futures[key].set_result(result)

    def stop(self):
        with self.wake:
            self.wake.notify_all()
        self.worker.join(timeout=3.0)


class RemoteAction:
    """Blocking API only for owned worker threads; ROS futures stay on the executor."""
    def __init__(self, node, action_type, endpoint):
        self.client = ActionClient(node, action_type, node.topic(endpoint), callback_group=node.group,
                                   goal_service_qos_profile=node.qos('action_control', 10),
                                   result_service_qos_profile=node.qos('action_control', 10),
                                   cancel_service_qos_profile=node.qos('action_control', 10),
                                   feedback_sub_qos_profile=node.qos('action_feedback', 10),
                                   status_sub_qos_profile=node.qos('action_status', 10, transient=True))

    @staticmethod
    def wait(future, op):
        while not future.done():
            op.pause(0.01)
        op.check()
        return future.result()

    def call(self, goal, op, feedback=None, on_accept=None):
        if not self.client.server_is_ready():
            raise AiError(Code.UNAVAILABLE, 'action server unavailable')
        future = self.client.send_goal_async(goal, feedback_callback=feedback)
        try:
            handle = self.wait(future, op)
        except AiError as original:
            # A cancellation can race the goal response. Keep the executor alive
            # while establishing the remote terminal state within a separate budget.
            cleanup = Operation(2.0)
            try:
                late = self.wait(future, cleanup)
                if late.accepted:
                    terminal = late.get_result_async()
                    self.wait(late.cancel_goal_async(), cleanup)
                    self.wait(terminal, cleanup)
            except AiError:
                future.add_done_callback(lambda f: f.result().cancel_goal_async() if f.result() and f.result().accepted else None)
                raise AiError(Code.TIMEOUT, 'remote termination unconfirmed: goal acceptance timed out; late acceptance will be canceled')
            raise original
        if not handle.accepted:
            raise AiError(Code.UNAVAILABLE, 'goal rejected; query AI service status')
        result_future = handle.get_result_async()
        try:
            if on_accept:
                on_accept(handle)
            result = self.wait(result_future, op)
            if not result.result.success:
                raise AiError(result.result.error_code, result.result.error_message)
            return result.result
        except Exception:
            cancel = handle.cancel_goal_async()
            cleanup = Operation(2.0)
            try:
                self.wait(cancel, cleanup)
                self.wait(result_future, cleanup)
            except AiError:
                # The caller must degrade rather than start conflicting work.
                raise AiError(Code.TIMEOUT, 'remote termination unconfirmed; manual recovery required')
            raise


def spin(factory):
    # Keep ROS alive during bounded worker cancellation. Repeated launch signals
    # only set the event; they cannot interrupt resource destruction midway.
    import signal
    from rclpy.signals import SignalHandlerOptions
    done = threading.Event()
    old_handlers = {sig: signal.signal(sig, lambda *_: done.set())
                    for sig in (signal.SIGINT, signal.SIGTERM)}
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node, executor, thread = None, None, None
    errors = []
    try:
        node = factory()
        executor = MultiThreadedExecutor(num_threads=4)
        executor.add_node(node)

        def run_executor():
            try:
                executor.spin()
            except Exception as exc:
                errors.append(exc)
                done.set()

        thread = threading.Thread(target=run_executor, name='ros_executor')
        thread.start()
        done.wait()
    finally:
        if node:
            node.stop()
        if executor:
            executor.shutdown(timeout_sec=3.0)
        if thread:
            thread.join(timeout=3.0)
        if node:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
    if errors:
        raise errors[0]
