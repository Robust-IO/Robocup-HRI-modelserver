import threading
import time
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from robocup_interfaces.msg import AiServiceStatus
from .core import PROTOCOL_VERSION
from .ros import AiNode, spin


class DiagnosticsNode(AiNode):
    def __init__(self, **kwargs):
        super().__init__('ai_diagnostics_node', 'diagnostics', **kwargs)
        # Status service is node-scoped for the two diagnostic processes.
        self.destroy_service(self.status_srv)
        from robocup_interfaces.srv import GetAiServiceStatus
        self.service = self.get_name()
        self.status_srv = self.create_service(GetAiServiceStatus, self.topic('ai/' + self.service + '/status'), self._status)
        self.required = self.param('diagnostics.required_services', ['tts', 'asr', 'llm'])
        self.expiry = self.param('diagnostics.expiry_sec', 2.0, minimum=0.5, maximum=30.0)
        self.records, self.lock = {}, threading.Lock()
        self.sub = self.create_subscription(AiServiceStatus, self.topic('ai/status'), self.receive, self.qos('peers', 20, transient=True))
        self.pub = self.create_publisher(DiagnosticArray, self.topic('ai/diagnostics'), self.qos('diagnostics', 10))
        self.timer = self.create_timer(0.5, self.check)

    def receive(self, msg):
        if msg.service_name in self.required:
            with self.lock:
                self.records[msg.service_name] = (msg, time.monotonic())

    def check(self):
        statuses = []
        with self.lock:
            for name in self.required:
                entry = self.records.get(name)
                status = DiagnosticStatus(name=self.topic('ai/' + name), hardware_id=self.release)
                if entry is None or time.monotonic() - entry[1] > self.expiry:
                    status.level, status.message = DiagnosticStatus.ERROR, 'missing or stale heartbeat'
                else:
                    msg = entry[0]
                    mismatch = msg.protocol_version != PROTOCOL_VERSION
                    status.level = DiagnosticStatus.OK if msg.ready and not mismatch else DiagnosticStatus.ERROR
                    status.message = 'protocol mismatch' if mismatch else msg.message
                    status.values = [KeyValue(key=k, value=str(getattr(msg, k))) for k in
                                     ('backend', 'model', 'protocol_version', 'release_id', 'git_commit')]
                statuses.append(status)
        message = DiagnosticArray(status=statuses)
        message.header.stamp = self.get_clock().now().to_msg()
        self.pub.publish(message)
        ready = all(s.level == DiagnosticStatus.OK for s in statuses)
        self.set_status('ready' if ready else 'degraded', ready, 'all required services ready' if ready else 'inspect ai/diagnostics')


def main():
    spin(DiagnosticsNode)
