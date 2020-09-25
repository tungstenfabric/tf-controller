from cfgm_common.exceptions import NoIdError
from schema_transformer.resources._resource_base import ResourceBaseST


class VirtualPortGroupST(ResourceBaseST):
    _dict = {}
    obj_type = 'virtual_port_group'
    ref_fields = []

    def __init__(self, name, obj=None):
        self.name = name
        self.uuid = None
        self.update(obj)
        self.uuid = self.obj.uuid
        self.pi_uuid_to_vmi_st_names = dict()
        # uuid of placeholder VMI
        self.virtual_machine_interface_uuid = None
        self.vlan_id = None
    # end __init__

    def update(self, obj=None):
        changed = self.update_vnc_obj(obj)
        return changed
    # end update

    def delete_obj(self):
        try:
            self._vnc_lib.virtual_machine_interface_delete(
                id=self.virtual_machine_interface)
        except NoIdError:
            pass

    def evaluate(self, **kwargs):
        self.validate_physical_interfaces()
        self.validate_virtual_port_group()
    # end evaluate

    def validate_physical_interfaces(self):
        for pi_uuid, vmi_st_names in self.pi_uuid_to_vmi_st_names.items():
            for vmi_st_name in vmi_st_names:
                vmi_st = ResourceBaseST.get_obj_type_map() \
                    .get('virtual_machine_interface').get(vmi_st_name)
                if vmi_st is None:
                    vmi_st_names.remove(vmi_st_name)
                    continue
                vlan_id = vmi_st.vlan_id
                vmi_pi_uuid = vmi_st.physical_interface_uuid
                if vlan_id != self.vlan_id or vmi_pi_uuid != pi_uuid:
                    vmi_st_names.remove(vmi_st_name)
            if len(vmi_st_names) == 0:
                del self.pi_uuid_to_vmi_st_names.delete[pi_uuid]
                try:
                    self._vnc_lib.ref_update(
                        'virtual-port-group', self.uuid, 'physical-interface',
                        pi_uuid, None, 'DELETE')
                except NoIdError:
                    # NoIdError raised if PI deleted while removing from VPG
                    pass
        return
    # end validate_physical_interfaces

    def validate_virtual_port_group(self):
        if len(self.pi_uuid_to_vmi_st_names) == 0:
            try:
                # no need to manually delete placeholder VMI,
                # since delete_obj will run when VPG deletion event is caught
                self._vnc_lib.virtual_port_group_delete(id=self.uuid)
            except NoIdError:
                pass
        return
    # end validate_virtual_port_group

    def update_virtual_machine_interface_uuid(
            self, virtual_machine_interface_uuid):
        self.virtual_machine_interface_uuid = virtual_machine_interface_uuid
        return
    # end update_virtual_machine_interface_uuid

    def update_vlan_id(self, vlan_id):
        self.vlan_id = vlan_id
        return
    # end update_vlan_id

    def update_pi_uuid_to_vmi_st_name(self, pi_uuid, vmi_st_name):
        self.pi_uuid_to_vmi_st_names[pi_uuid] = \
            self.pi_uuid_to_vmi_st_names.get(pi_uuid, []) + [vmi_st_name]
        return
    # end update_pi_uuid_to_vmi_st_name

# end class VirtualPortGroupST
