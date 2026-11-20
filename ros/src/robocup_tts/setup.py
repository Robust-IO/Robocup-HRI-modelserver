from pathlib import Path
from setuptools import find_packages, setup

name = 'robocup_tts'
data = [('share/ament_index/resource_index/packages', ['resource/' + name]),
        ('share/' + name, ['package.xml'])]
for folder in ('launch', 'config', 'prompts'):
    for directory in sorted({p.parent for p in Path(folder).rglob('*') if p.is_file()}):
        data.append(('share/' + name + '/' + str(directory),
                     [str(p) for p in sorted(directory.iterdir()) if p.is_file()]))
setup(name=name, version='0.1.0', packages=find_packages(exclude=['test']),
      data_files=data, install_requires=['setuptools'], zip_safe=True,
      maintainer='Nankai RoboCup Team', maintainer_email='robocup@nankai.edu.cn',
      description='Model independent RoboCup AI infrastructure', license='Proprietary',
      tests_require=['pytest'], entry_points={'console_scripts': ['tts_node = robocup_tts.node:main']})
