FROM ros:humble-ros-base
WORKDIR /opt/robocup
COPY --from=ai robocup_interfaces src/robocup_interfaces
COPY --from=ai robocup_ai_runtime src/robocup_ai_runtime
COPY --from=ai robocup_ai_bringup src/robocup_ai_bringup
COPY --from=ai robocup_llm src/robocup_llm
COPY --from=ai robocup_tts src/robocup_tts
COPY --from=ai robocup_asr src/robocup_asr
RUN . /opt/ros/humble/setup.sh && colcon build --merge-install --cmake-args -DBUILD_TESTING=OFF
COPY start.sh /opt/robocup/start.sh
CMD ["bash", "/opt/robocup/start.sh"]
