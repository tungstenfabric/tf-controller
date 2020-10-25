#
# Copyright (c) 2013 Juniper Networks, Inc. All rights reserved.
#

import re
from setuptools import setup, find_packages
import sys


def requirements(filename):
    with open(filename) as f:
        lines = f.read().splitlines()
    c = re.compile(r'\s*#.*')
    result = list(filter(bool, map(lambda y: c.sub('', y).strip(), lines)))
    if sys.version_info.major < 3 and 'gevent<1.5.0' in result:
        # current UT doesn't work with gevent==1.4.0 for python2
        # and gevent==1.1.2 can't be used with python3
        # Apply this workaround as markers are not supported in requirements.txt
        result.remove('gevent<1.5.0')
        result.append('gevent==1.1.2')
    return result


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
