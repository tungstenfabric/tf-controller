#
# Copyright (c) 2020 Juniper Networks, Inc. All rights reserved.
#

import re

from cfgm_common.tests import test_common


class UtilsTestCase(test_common.TestCase):
    def setUp(self):
        super(UtilsTestCase, self).setUp()
        self.ignore_err_in_log = False

    def tearDown(self):
        try:
            if self.ignore_err_in_log:
                return

            with open('api_server_%s.log' % (self.id())) as f:
                lines = f.read()
                self.assertIsNone(
                    re.search('SYS_ERR', lines), 'Error in log file')
        except IOError:
            # vnc_openstack.err not created, No errors.
            pass
        finally:
            super(UtilsTestCase, self).tearDown()

    @property
    def api(self):
        return self._vnc_lib

# end class UtilsTestCase
