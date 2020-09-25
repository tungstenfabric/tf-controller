from cfgm_common.exceptions import NoIdError

from schema_transformer.resources._resource_base import ResourceBaseST


class VirtualPortGroupST(ResourceBaseST):
    _dict = {}
    obj_type = 'virtual_port_group'
    ref_fields = ['virtual_machine_interface']
    prop_fields = ['annotations']

    @classmethod
    def reinit(cls):
        ok, result, _ = cls._object_db.object_list(
            cls.obj_type,
            filters={
                'm:annotations:usage': {
                    'key': 'usage',
                    'value': 'sriov-vm'}})
        if not ok:
            cls._logger.error(
                "Listing virtual port groups failed during reinit")
            return
        for _, uuid in result:
            obj = cls.read_vnc_obj(uuid=uuid)
            st_obj = cls.locate(obj.get_fq_name_str(), obj)
            st_obj.evaluate()
    # end reinit

    def __init__(self, name, obj=None):
        self.name = name
        self.uuid = None
        self.virtual_machine_interfaces = set()
        self.update(obj)
        self.uuid = self.obj.uuid
    # end __init__

    def update(self, obj=None):
        changed = self.update_vnc_obj(obj)
        if 'annotations' in changed:
            self.set_annotations()
        return changed
    # end update

    def delete_obj(self):
        for fabric_vmi_st_name in self.virtual_machine_interfaces:
            fabric_vmi_st = \
                ResourceBaseST.get_obj_type_map() \
                              .get('virtual_machine_interface') \
                              .get(fabric_vmi_st_name)
            self.delete_fabric_vmi_ref(fabric_vmi_st)
    # end delete_obj

    def evaluate(self, **kwargs):
        if getattr(self, 'annotations', {}).get("usage", "") == "sriov-vm":
            self.sanitize_fabric_vmis()
            if not self.is_valid():
                self.delete_self_db_obj()
    # end evaluate

    def sanitize_fabric_vmis(self):
        self._logger.notice("Starts sanitizing "
                            "vpg's (%s) fabric vmis" % self.name)
        for fabric_vmi_st_name in self.virtual_machine_interfaces:
            fabric_vmi_st = \
                ResourceBaseST.get_obj_type_map() \
                              .get('virtual_machine_interface') \
                              .get(fabric_vmi_st_name)
            if fabric_vmi_st is None:
                continue
            vn_st = \
                ResourceBaseST.get_obj_type_map() \
                              .get('virtual_network') \
                              .get(fabric_vmi_st.virtual_network)
            if vn_st is None:
                continue
            vn_st.virtual_port_groups.add(self.name)
            no_valid_vmi_under_fabric_vmi = True
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
                        no_valid_vmi_under_fabric_vmi = False
                        break
            if no_valid_vmi_under_fabric_vmi:
                self.delete_fabric_vmi_ref(fabric_vmi_st)
        self._logger.notice("Finshed sanitizing "
                            "vpg's (%s) fabric vmis" % self.name)
    # end sanitize_fabric_vmis

    def is_valid(self):
        self.update(None)
        if len(self.virtual_machine_interfaces) == 0:
            return False
        return True
    # end is_valid

    def delete_self_db_obj(self):
        self._logger.notice("Starts deleting vpg db object %s" % self.name)
        try:
            # no need to manually delete fabric VMI,
            # since delete_obj will run when VPG deletion event is caught
            self.delete_obj()
            self._vnc_lib.virtual_port_group_delete(id=self.uuid)
        except NoIdError:
            pass
        self._logger.notice("Finished deleting vpg db object %s" % self.name)
    # end delete_self_db_obj

    def delete_fabric_vmi_ref(self, fabric_vmi_st):
        if fabric_vmi_st is not None:
            vn_st = \
                ResourceBaseST.get_obj_type_map() \
                              .get('virtual_network') \
                              .get(fabric_vmi_st.virtual_network)
            if vn_st is not None:
                if self.name in vn_st.virtual_port_groups:
                    vn_st.virtual_port_groups.remove(self.name)
            fabric_vmi_uuid = fabric_vmi_st.uuid
            if fabric_vmi_uuid is not None:
                try:
                    self._vnc_lib.ref_update(
                        'virtual-port-group', self.uuid,
                        'virtual-machine-interface', fabric_vmi_uuid,
                        None, 'DELETE')
                    fabric_vmi = self._vnc_lib \
                                     .virtual_machine_interface_read(
                                         id=fabric_vmi_uuid)
                    if len(fabric_vmi.get_virtual_port_group_back_refs()) == 0:
                        self._vnc_lib \
                            .virtual_machine_interface_delete(
                                id=fabric_vmi_uuid)
                except NoIdError:
                    pass
                except Exception as e:
                    self._logger.error("Unexpected error during "
                                       "dereferencing fabric vmi %s: %s"
                                       % (fabric_vmi_st.name, e.msg))
    # end delete_fabric_vmi_ref

    def get_uuids(self, items):
        if items is None:
            return []
        if isinstance(items, list):
            return [item['uuid'] for item in items]
        if isinstance(items, dict) and len(items.keys()) > 0:
            return [item['uuid'] for item in
                    items.get(list(items.keys())[0], [])]
    # end get_uuids

    def set_annotations(self):
        self.annotations = self.kvps_to_dict(self.obj.get_annotations())
        return
    # end set_bindings

    def kvps_to_dict(self, kvps):
        dictionary = dict()
        if not kvps:
            return dictionary
        for kvp in kvps.get_key_value_pair():
            dictionary[kvp.get_key()] = kvp.get_value()
        return dictionary
    # end kvps_to_dict

# end class VirtualPortGroupST
