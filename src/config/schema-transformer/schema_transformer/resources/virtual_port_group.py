from cfgm_common.exceptions import NoIdError
from schema_transformer.resources._resource_base import ResourceBaseST


class VirtualPortGroupST(ResourceBaseST):
    _dict = {}
    obj_type = 'virtual_port_group'
    ref_fields = ['virtual_machine_interface']

    def __init__(self, name, obj=None):
        self.name = name
        self.uuid = None
        self.virtual_machine_interfaces = set()
        self.update(obj)
        self.uuid = self.obj.uuid
        self.physical_interface_uuids = set()
    # end __init__

    def update(self, obj=None):
        changed = self.update_vnc_obj(obj)
        return changed
    # end update

    def delete_obj(self):
        for placeholder_vmi_st_name in self.virtual_machine_interfaces:
            placeholder_vmi_st = \
                ResourceBaseST.get_obj_type_map() \
                              .get('virtual_machine_interface') \
                              .get(placeholder_vmi_st_name)
            placeholder_vmi_uuid = placeholder_vmi_st.uuid
            if placeholder_vmi_uuid is not None:
                try:
                    self._vnc_lib.ref_update(
                        'virtual-port-group', self.uuid,
                        'virtual-machine-interface', placeholder_vmi_uuid,
                        None, 'DELETE')
                    self._vnc_lib.virtual_machine_interface_delete(
                        id=placeholder_vmi_uuid)
                except NoIdError:
                    continue
    # end delete_obj

    def evaluate(self, **kwargs):
        self.update_physical_interfaces()
        self.validate_virtual_port_group()
    # end evaluate

    def update_physical_interfaces(self):
        new_pis = set()
        placeholder_vmi_st = None
        for placeholder_vmi_st_name in self.virtual_machine_interfaces:
            placeholder_vmi_st = \
                ResourceBaseST.get_obj_type_map() \
                              .get('virtual_machine_interface') \
                              .get(placeholder_vmi_st_name)
        if placeholder_vmi_st is None:
            return
        vn_st = \
            ResourceBaseST.get_obj_type_map() \
                          .get('virtual_network') \
                          .get(placeholder_vmi_st.virtual_network)
        if vn_st is None:
            return
        for vmi_st_name in vn_st.virtual_machine_interfaces:
            vmi_st = \
                ResourceBaseST.get_obj_type_map() \
                              .get('virtual_machine_interface') \
                              .get(vmi_st_name)
            if vmi_st is None:
                continue
            # update vmi's virtual_port_group field
            vmi_st.virtual_port_group = self.name
            # add pi_uuid
            if vmi_st.physical_interface_uuid is not None:
                new_pis.add(vmi_st.physical_interface_uuid)
        old_pis = self.physical_interface_uuids
        if old_pis == new_pis:
            return
        # delete pi refs and update pi refs
        for pi_uuid in old_pis - new_pis:
            self._vnc_lib.ref_update(
                'virtual-port-group', self.uuid, 'physical-interface',
                pi_uuid, None, 'DELETE')
        for pi_uuid in new_pis - old_pis:
            self._vnc_lib.ref_update(
                'virtual-port-group', self.uuid, 'physical-interface',
                pi_uuid, None, 'ADD')
        # update physical_interface_uuids field
        self.physical_interface_uuids = new_pis
    # end update_physical_interfaces

    def validate_virtual_port_group(self):
        if len(self.physical_interface_uuids) == 0:
            try:
                # no need to manually delete placeholder VMI,
                # since delete_obj will run when VPG deletion event is caught
                # TODO(dji): will this delet cause problem since vmi
                # is still there,
                # yes, need to delete ref first, need test
                self.delete_obj()
                self._vnc_lib.virtual_port_group_delete(id=self.uuid)
            except NoIdError:
                pass
    # end validate_virtual_port_group

# end class VirtualPortGroupST
