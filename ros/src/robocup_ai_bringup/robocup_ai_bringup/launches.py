from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from pathlib import Path


def role_launch(role):
    share = Path(get_package_share_directory('robocup_ai_bringup'))
    industrial = role == 'industrial_pc'
    services = [('microphone', 'robocup_audio_io', 'microphone_capture_node'),
                ('speaker', 'robocup_audio_io', 'speaker_player_node'),
                ('orchestrator', 'robocup_ai_orchestrator', 'ai_orchestrator_node')] if industrial else [
                    ('tts', 'robocup_tts', 'tts_node'), ('asr', 'robocup_asr', 'asr_node'), ('llm', 'robocup_llm', 'llm_node')]
    args = [DeclareLaunchArgument('robot_namespace', default_value='/robot1'),
            DeclareLaunchArgument('common_config', default_value=str(share / 'config/common.yaml')),
            DeclareLaunchArgument('role_config', default_value=str(share / 'config' / (role + '.yaml'))),
            DeclareLaunchArgument('release_id', default_value='development'),
            DeclareLaunchArgument('git_commit', default_value='unknown'),
            DeclareLaunchArgument('enable_diagnostics', default_value='true')]
    if not industrial:
        args.append(DeclareLaunchArgument('asr_input', default_value='frames', choices=['frames', 'wav']))
    for name, _, _ in services:
        args.append(DeclareLaunchArgument('enable_' + name, default_value='true'))
        if not industrial:
            args.append(DeclareLaunchArgument(name + '_config', default_value=str(share / 'config' / (name + '.yaml'))))

    def launch(context):
        def value(name):
            return LaunchConfiguration(name).perform(context)
        ns = value('robot_namespace')
        common = [value('common_config'), value('role_config')]
        override = dict(robot_namespace=ns, release_id=value('release_id'), git_commit=value('git_commit'))
        nodes, enabled = [], []
        for name, package, executable in services:
            flag = value('enable_' + name).lower()
            if flag not in ('true', 'false'):
                raise ValueError('enable flags must be true/false')
            if flag == 'false':
                continue
            if name == 'asr' and value('asr_input') == 'wav':
                executable = 'transcribe_wav_node'
                enabled.append('asr_wav')
            else:
                enabled.append(name)
            parameters = common + ([] if industrial else [value(name + '_config')])
            if name == 'orchestrator':
                prompts = Path(get_package_share_directory('robocup_audio_io')) / 'prompts'
                parameters = [{'flow.fallback_pcm': str(prompts / 'service_unavailable.pcm'),
                               'flow.network_lost_pcm': str(prompts / 'network_lost.pcm')}] + parameters
            nodes.append(Node(package=package, executable=executable, namespace=ns,
                              parameters=parameters + [override], output='screen'))
        if value('enable_diagnostics').lower() == 'true':
            nodes.append(Node(package='robocup_ai_runtime', executable='ai_diagnostics_node', namespace=ns,
                              name=role + '_diagnostics', parameters=common + [override, {'diagnostics.required_services': enabled}], output='screen'))
        return nodes
    return LaunchDescription(args + [OpaqueFunction(function=launch)])
