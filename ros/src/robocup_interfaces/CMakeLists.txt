cmake_minimum_required(VERSION 3.8)
project(robocup_interfaces)
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
find_package(action_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(sensor_msgs REQUIRED)
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/AudioChunk.msg"
  "msg/AiServiceStatus.msg"
  "action/Speak.action"
  "action/TranscribeWav.action"
  "action/Chat.action"
  "action/PlayAudio.action"
  "action/ParseUtterance.action"
  "action/RequestTaskPlan.action"
  "srv/GetAiServiceStatus.srv"
  DEPENDENCIES std_msgs action_msgs builtin_interfaces sensor_msgs)
ament_export_dependencies(rosidl_default_runtime)
ament_package()
