#
# Copyright (c) 2013 Juniper Networks, Inc. All rights reserved.
#

import re
from setuptools import setup, find_packages


def requirements(filename):
    with open(filename) as f:
        lines = f.read().splitlines()
    c = re.compile(r'\s*#.*')
    return list(filter(bool, map(lambda y: c.sub('', y).strip(), lines)))


setup(
    name='contrail_config_utils',
    version='0.1dev',
    packages=find_packages(),
    package_data={'': ['*.xml']},
    zip_safe=False,
    description="Contrail VNC Configuration Utils",
    long_description="Contrail VNC Configuration Utils",
    install_requires=requirements('requirements.txt'),
    tests_require=requirements('test-requirements.txt'),
    test_suite='contrail_config_utils.tests',
)
