from cfgm_common.exceptions import NoIdError

from schema_transformer.resources._resource_base import ResourceBaseST


class VirtualPortGroupST(ResourceBaseST):
    _dict = {}
    obj_type = 'virtual_port_group'
    ref_fields = ['virtual_machine_interface']
    prop_fields = ['virtual_port_group_user_created']

    @classmethod
    def reinit(cls):
        for obj in cls.list_vnc_obj():
            st_obj = cls.locate(obj.get_fq_name_str(), obj)
            st_obj.evaluate()
    # end reinit

    def __init__(self, name, obj=None):
        self.name = name
        self.uuid = None
        self.virtual_port_group_user_created = True
        self.virtual_machine_interfaces = set()
        self.update(obj)
        self.uuid = self.obj.uuid
    # end __init__

    def update(self, obj=None):
        changed = self.update_vnc_obj(obj)
        return changed
    # end update

    def delete_obj(self):
        for fabric_vmi_st_name in self.virtual_machine_interfaces:
            fabric_vmi_st = \
                ResourceBaseST.get_obj_type_map() \
                              .get('virtual_machine_interface') \
                              .get(fabric_vmi_st_name)
            if fabric_vmi_st is None:
                continue
            fabric_vmi_uuid = fabric_vmi_st.uuid
            if fabric_vmi_uuid is not None:
                try:
                    self._vnc_lib.ref_update(
                        'virtual-port-group', self.uuid,
                        'virtual-machine-interface', fabric_vmi_uuid,
                        None, 'DELETE')
                    self._vnc_lib.virtual_machine_interface_delete(
                        id=fabric_vmi_uuid)
                except NoIdError:
                    continue
    # end delete_obj

    def evaluate(self, **kwargs):
        if not self.virtual_port_group_user_created:
            if self.is_virtual_port_group_valid():
                self.delete_vpg_object()
    # end evaluate

    def is_virtual_port_group_valid(self):
        self._logger.notice("Starts validating vpg st object %s" % self.name)
        valid_vmi_exist = False
        for fabric_vmi_st_name in self.virtual_machine_interfaces:
            fabric_vmi_st = \
                ResourceBaseST.get_obj_type_map() \
                              .get('virtual_machine_interface') \
                              .get(fabric_vmi_st_name)
            if fabric_vmi_st is None:
                continue
            fabric_vmi_st.virtual_port_group = self.name
            vn_st = \
                ResourceBaseST.get_obj_type_map() \
                              .get('virtual_network') \
                              .get(fabric_vmi_st.virtual_network)
            if vn_st is None:
                continue
            for vmi_st_name in vn_st.virtual_machine_interfaces:
                if vmi_st_name != fabric_vmi_st_name:
                    vmi_st = \
                        ResourceBaseST.get_obj_type_map() \
                                      .get('virtual_machine_interface') \
                                      .get(vmi_st_name)
                    if vmi_st is None:
                        continue
                    if vmi_st.physical_interface_uuid in \
                       self.get_uuids(self.obj.get_physical_interface_refs()):
                        vmi_st.virtual_port_group = self.name
                        # If any vmi has the same pi as this vpg refs
                        # then this vpg is valid
                        valid_vmi_exist = True
        self._logger.notice("Finshed validating vpg st object %s" % self.name)
        return valid_vmi_exist
    # end is_virtual_port_group_valid

    def delete_vpg_object(self):
        self._logger.notice("Starts deleting vpg object %s" % self.name)
        try:
            # no need to manually delete fabric VMI,
            # since delete_obj will run when VPG deletion event is caught
            self.delete_obj()
            self._vnc_lib.virtual_port_group_delete(id=self.uuid)
        except NoIdError:
            pass
        self._logger.notice("Finished deleting vpg object %s" % self.name)
    # end delete_vpg_object

    def get_uuids(self, items):
        if items is None:
            return []
        if isinstance(items, list):
            return [item['uuid'] for item in items]
        if isinstance(items, dict) and len(items.keys()) > 0:
            return [item['uuid'] for item in
                    items.get(list(items.keys())[0], [])]
    # end get_uuids

# end class VirtualPortGroupST
