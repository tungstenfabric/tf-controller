#
# Copyright (c) 2014 Juniper Networks, Inc. All rights reserved.
#

"""This file implements abstract config generation."""

from abstract_device_api.abstract_device_xsd import *

from .ansible_conf import AnsibleConf


class OverlayConf(AnsibleConf):
    """Public class for Overlay config."""

    _roles = ['leaf', 'pnf', 'spine', 'superspine']

    def __init__(self, logger, params={}):
        """Init routine for overlay config."""
        super(OverlayConf, self).__init__(logger, params)
    # end __init__

    @classmethod
    def register(cls):
        """."""
        qconf = {
              "roles": cls._roles,
              "class": cls
            }
        return super(OverlayConf, cls).register(qconf)
    # end register

    def push_conf(self, feature_configs=None, is_delete=False):
        """."""
        if not self.physical_router:
            return 0
        if is_delete:
            return self.send_conf(is_delete=True)
        return self.send_conf(feature_configs=feature_configs)
    # end push_conf

# end LeafConf
