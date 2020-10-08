#!/usr/bin/python

#
# Copyright (c) 2019 Juniper Networks, Inc. All rights reserved.
#

from builtins import object


class FilterModule(object):
    def filters(self):
        return {
            'is_juniper_device_online': self.is_juniper_device_online
        }
    # end filters

    @classmethod
    def is_juniper_device_online(cls, fpc_pic_status_info):
        msg = list()
        out = dict()
        if not fpc_pic_status_info or \
                not fpc_pic_status_info.get('fpc-information') or \
                not fpc_pic_status_info.get('fpc-information').get('fpc'):
            out['status'] = False
            out['msg'] = 'failed to get fpc-information'
            return out
        fpc_slots = fpc_pic_status_info.get('fpc-information').get('fpc')
        if isinstance(fpc_slots, dict):
            fpc_slots = [fpc_slots]
        for fpc in fpc_slots:
            if not fpc.get('state') or fpc.get('state').lower() != 'online':
                msg.append("fpc at slot {0} is {1}".
                           format(fpc.get('slot', ''),
                                  fpc.get('state', 'Offline')))
                continue
            pic_slots = fpc.get('pic')
            if pic_slots is None:
                msg.append("fpc at slot {0} has no pics".format(
                    fpc.get('slot', '')))
                continue
            if isinstance(pic_slots, dict):
                pic_slots = [pic_slots]
            for pic in pic_slots:
                if not pic.get('pic-state') or \
                        pic.get('pic-state').lower() != 'online':
                    msg.append("pic at pic-slot {0} of fpc slot {1} is {2}".
                               format(pic.get('pic-slot', ''),
                                      fpc.get('slot', ''),
                                      pic.get('state', 'Offline')))
                    continue
        out['status'] = True
        out['msg'] = ('; '.join(msg))
        return out
    # end is_juniper_device_online
# end FilterModule
