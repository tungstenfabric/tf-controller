template <class ItType>
bool VxlanRoutingManager::IsExternalType5(ItType *item, const Agent *agent) {
    return IsExternalType5(ItemNexthopsToVector(item), agent);
}

template <class ItType>
std::vector<IpAddress> VxlanRoutingManager::ItemNexthopsToVector(ItType *item) {
    std::vector<IpAddress> nh_addr;
    const uint32_t n_items = item->entry.next_hops.next_hop.size();
    for (uint32_t i_nh=0; i_nh < n_items; i_nh++) {
        const IpAddress nh_ip = IpAddress::from_string(
            item->entry.next_hops.next_hop[i_nh].address);
        nh_addr.insert(nh_addr.end(), nh_ip);
    }

    return nh_addr;
}

template<typename NhType>
void VxlanRoutingManager::AddInterfaceComponentToList(
    const std::string& prefix_str,
    const std::string& vrf_name,
    const NhType &nh_item,
    ComponentNHKeyList& comp_nh_list) {
    const Agent *agent = Agent::GetInstance();
    IpAddress ip_addr;
    uint32_t prefix_len;
    boost::system::error_code ec;

    if (is_ipv4_string(prefix_str)) {
        ip_addr = Ip4Address::from_string(ipv4_prefix(prefix_str), ec);
        prefix_len = ipv4_prefix_len(prefix_str);
    } else if (is_ipv6_string(prefix_str)) {
        std::string addr_str = ipv6_prefix(prefix_str);
        prefix_len = ipv6_prefix_len(prefix_str);
        ip_addr = Ip6Address::from_string(addr_str, ec);
    } else {
        LOG(ERROR, "Error in VxlanRoutingManager::AddInterfaceComponentToList"
            << ", prefix_str = " << prefix_str
            << " is not an IPv4 or IPv6 prefix");
        return;
    }

    if (ec) {
        LOG(ERROR, "Possible error in "
            << "VxlanRoutingManager::AddInterfaceComponentToList"
            << ", cannot convert prefix_str = " << prefix_str
            << " to IPv4 or IPv6 address");
        return;
    }

    const AgentRoute *intf_rt =
        FindEvpnOrInetRoute(agent, vrf_name, ip_addr, prefix_len, nh_item);
    if (intf_rt == NULL) {
        return;
    }

    const AgentPath *loc_path =
        intf_rt->FindIntfOrCompLocalVmPortPath();
    if (loc_path == NULL) {
        return;
    }
    if (loc_path->nexthop() == NULL) {
        return;
    }

    // Case 1. NextHop is an interface
    if (loc_path->nexthop()->GetType() == NextHop::INTERFACE) {
        DBEntryBase::KeyPtr key_ptr =
            loc_path->nexthop()->GetDBRequestKey();
        NextHopKey *nh_key =
            static_cast<NextHopKey *>(key_ptr.release());
        std::auto_ptr<const NextHopKey> nh_key_ptr(nh_key);
        ComponentNHKeyPtr component_nh_key(new ComponentNHKey(MplsTable::kInvalidLabel,  // label
                                        nh_key_ptr));
        comp_nh_list.push_back(component_nh_key);
        return;
    }

    // Case 2. NextHop is a composite of interfaces
    // Copy all interfaces from this composite
    // into the components list
    if (loc_path->nexthop()->GetType() == NextHop::COMPOSITE) {
        CompositeNH *loc_comp_nh = dynamic_cast<CompositeNH*>
            (loc_path->nexthop());

        DBEntryBase::KeyPtr key_ptr =
            loc_comp_nh->GetDBRequestKey();
        CompositeNHKey *nh_key =
            static_cast<CompositeNHKey *>(key_ptr.release());
        std::auto_ptr<const NextHopKey> nh_key_ptr(nh_key);

        if (nh_key == NULL){
            LOG(ERROR, "Error in VxlanRoutingManager::AddInterfaceComponentToList"
            << ", null nh key");
            assert(nh_key != NULL);
        }

        // Refresh on path_preference.sequence change
        const ComponentNHList& component_nh_list =
            loc_comp_nh->component_nh_list();
        for (ComponentNHList::const_iterator
            it_nh = component_nh_list.begin();
            it_nh != component_nh_list.end(); it_nh++) {
            // nullptr means deleted component, which
            // can be reused later
            std::auto_ptr<const NextHopKey> nh_key_ptr;
            ComponentNHKeyPtr component_nh_key;
            if (it_nh->get() == NULL) {
                // component_nh_key.reset(NULL);
            } else {
                DBEntryBase::KeyPtr key =
                    it_nh->get()->nh()->GetDBRequestKey();
                NextHopKey *nh_key =
                    static_cast<NextHopKey *>(key.release());
                nh_key_ptr.reset(nh_key);
                component_nh_key.reset(
                    new ComponentNHKey(MplsTable::kInvalidLabel, nh_key_ptr));
            }
            comp_nh_list.push_back(component_nh_key);
        }
    }
}  // AddInterfaceComponentToList func

//
// END-OF-FILE
//
