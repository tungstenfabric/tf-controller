/*
 * Copyright (c) 2023 Matvey Kraposhin 
 */
extern "C" {
    #include <errno.h>
    #include <net/if.h>
    #include <sys/socket.h>
    #include <unistd.h>
    #include <linux/netlink.h>
    #include <linux/rtnetlink.h>
    #include <linux/neighbour.h>
    #include <linux/if_addr.h>
    #include <arpa/inet.h>
}
#include <cstring>
#include <cmn/agent_cmn.h>
#include <oper/interface_common.h>
#include <oper/route_common.h>
#include <oper/inet_unicast_route.h>
#include <oper/global_vrouter.h>
#include "services/metadata_proxy.h"
#include "services/metadata_server.h"
#include "services/services_init.h"

int MetadataProxy::VhostIndex(const std::string& vhost_name) {
    if (vhost_name != std::string("")) {
        int intf_idx = if_nametoindex(vhost_name.c_str());
        if (intf_idx > 0)
            return intf_idx;
    }
    return 0;
}

void MetadataProxy::AnnounceVhostRoute(const std::string& vrf_name) {
    const VrfEntry* u_vrf =
        this->services_->agent()->vrf_table()->FindVrfFromName(vrf_name);
    AnnounceVhostRoute(u_vrf);
}

void MetadataProxy::AnnounceVhostRoute(const VrfEntry* vrf_entry) {
    if (vrf_entry == NULL)
        return;
    if (this->services_->agent() == NULL ||
        this->services_->agent()->vhost_interface() == NULL)
        return;

    if (vrf_entry == services_->agent()->fabric_vrf() ||
        vrf_entry == services_->agent()->fabric_policy_vrf())
        return;

    IpAddress t_ip = Ipv6ServiceAddress();

    InetUnicastAgentRouteTable *inet_table =
        vrf_entry->GetInetUnicastRouteTable(t_ip);
    if (inet_table == NULL)
        return;

    PathPreference path_preference;
    VnListType vn_list;
    if (vrf_entry->vn())
       vn_list.insert(vrf_entry->vn()->GetName());

    boost::uuids::uuid vhost_uuid = boost::uuids::nil_uuid();
    if (this->services_->agent()->vhost_interface()) {
        vhost_uuid = this->services_->agent()->vhost_interface()->GetUuid();
    }

    const VmInterface *cvhost0 = dynamic_cast<const VmInterface *>
        (this->services_->agent()->vhost_interface());
    if (!cvhost0) {
        return;
    }

    cvhost0->SetPathPreference(&path_preference, cvhost0->ecmp6(), t_ip);
    SecurityGroupList sg_list;
    TagList tag_list;

    // IPV6_ALL_NODES_ADDRESS (see for example Icmpv6)
    // InetUnicastAgentRouteTable::AddHostRoute ???

    inet_table->AddLocalVmRoute(
        this->services_->agent()->local_vm_peer(),
        vrf_entry->GetName(),
        t_ip,
        128,
        vhost_uuid,
        vn_list,
        cvhost0->label(),  // label
        sg_list,
        tag_list,
        CommunityList(),
        false,
        path_preference,
        Ip6Address(),
        cvhost0->ecmp_load_balance(),
        true,  // is_local
        false,
        this->services_->agent()->vhost_interface_name(),
        true);  // native_encap
}

void MetadataProxy::AnnounceVhostRoutes() {
    VrfTable *vrf_table = this->services_->agent()->vrf_table();
    DBTablePartBase *c_part = NULL;
    VrfEntry *c_vrf;
    InetUnicastAgentRouteTable *c_table;

    if (!vrf_table)
        return;
    // loop over  all partitions
    for (int i_part = 0; i_part < vrf_table->PartitionCount(); i_part++) {
        c_part = vrf_table->GetTablePartition(i_part);
        if (!c_part)
            continue;

        // loop over vrfs
        c_vrf = dynamic_cast<VrfEntry*>(c_part->GetFirst());
        while (c_vrf) {
            c_table = c_vrf->GetInet6UnicastRouteTable();

            if (c_table) {
                this->AnnounceVhostRoute(c_vrf);
            }
            c_vrf = dynamic_cast<VrfEntry*>(c_part->GetNext(c_vrf));
        }
    }
}

void MetadataProxy::DeleteVhostRoute(const VrfEntry* vrf_entry) {
    const VmInterface* vhost_intf = NULL;
    DBEntryBase::KeyPtr tvhost_key_ptr;
    InetUnicastRouteEntry *c_entry = NULL;
    const AgentPath *local_path = NULL;
    InterfaceNH *intf_nh = NULL;
    const MplsLabel *intf_mpls = NULL;

    if (!vrf_entry)
        return;

    const std::string policy_vrf = this->services_->agent()->
        fabric_policy_vrf_name();
    const std::string fabric_vrf = this->services_->agent()->
        fabric_vrf_name();

    vhost_intf = dynamic_cast<const VmInterface *>
        (this->services_->agent()->vhost_interface());
    if (!vhost_intf)
        return;
    tvhost_key_ptr = vhost_intf->GetDBRequestKey();
    const VmInterfaceKey* vhost_key_ptr =
        dynamic_cast<const VmInterfaceKey *>(tvhost_key_ptr.get());
    if (!vhost_key_ptr)
        return;

    const IpAddress ip_addr = this->Ipv6ServiceAddress();

    c_entry = vrf_entry->GetUcRoute(ip_addr);
    if (!c_entry ||
        vrf_entry->GetName() == policy_vrf ||
        vrf_entry->GetName() == fabric_vrf)
        return;

    local_path = c_entry->GetActivePath();
    if (!local_path)
        return;

    uint8_t intf_flags = 0;
    uint32_t mpls_label = 0;
    intf_nh = dynamic_cast<InterfaceNH *>
        (local_path->nexthop());
    if (intf_nh)
        intf_flags = intf_nh->GetFlags();
    intf_mpls = local_path->nexthop()->mpls_label();
    if (intf_mpls)
        mpls_label = intf_mpls->label();
    LocalVmRoute *loc_rt_ptr = new LocalVmRoute(
        *vhost_key_ptr,
        mpls_label,  // mpls_label
        local_path->vxlan_id(),
        local_path->force_policy(),
        local_path->dest_vn_list(),
        intf_flags,  // flags
        local_path->sg_list(),
        local_path->tag_list(),
        local_path->communities(),
        local_path->path_preference(),
        local_path->subnet_service_ip(),
        local_path->ecmp_load_balance(),
        local_path->is_local(),
        local_path->is_health_check_service(),
        local_path->sequence(),
        local_path->etree_leaf(),
        true);  // native_encap

    vrf_entry->GetInet6UnicastRouteTable()->Delete(
        local_path->peer(),
        vrf_entry->GetName(),
        ip_addr, c_entry->plen(),
        loc_rt_ptr);
}

void MetadataProxy::DeleteVhostRoutes() {
    VrfTable *vrf_table = this->services_->agent()->vrf_table();
    DBTablePartBase *c_part = NULL;
    VrfEntry *c_vrf = NULL;

    if (!vrf_table)
        return;

    // loop over all partitions
    for (int i_part = 0; i_part < vrf_table->PartitionCount(); i_part++) {
        c_part = vrf_table->GetTablePartition(i_part);
        if (!c_part)
            continue;
        // loop over vrfs
        c_vrf = dynamic_cast<VrfEntry*>(c_part->GetFirst());
        while (c_vrf) {
            DeleteVhostRoute(c_vrf);
            c_vrf = dynamic_cast<VrfEntry*>(c_part->GetNext(c_vrf));
        }
    }
}

void MetadataProxy::AnnounceMetaDataLinkLocalRoutes(const VmInterface* vm_intf,
    const Ip6Address& ll_ip, const VrfEntry* intf_vrf) {
    if (vm_intf == NULL || intf_vrf == NULL) {
        return;
    }

    tbb::mutex::scoped_lock lock(ll_ipv6_addr_mutex_);

    const VrfEntry* vhost_vrf =
        vm_intf->agent()->fabric_vrf();

    InterfaceTable* intf_table = vm_intf->agent()->interface_table();
    intf_table->LinkVmPortToMetaDataIp(vm_intf, ll_ip);

    {
        InetUnicastAgentRouteTable *intf_inet_table =
            intf_vrf->GetInet6UnicastRouteTable();
        if (intf_inet_table == NULL)
            return;
        InetUnicastRouteEntry* rt_entry =
            intf_inet_table->FindRoute(ll_ip);
        if (rt_entry != NULL) {
            return;
        }
        VnListType vn_list;
        if (vm_intf->vn())
            vn_list.insert(vm_intf->vn()->GetName());

        InetInterfaceKey intf_key(vm_intf->name());
        InetInterfaceRoute *data = new InetInterfaceRoute
            (intf_key, vm_intf->label(), TunnelType::MplsType(),
            vn_list, vm_intf->peer()->sequence_number());

        DBRequest req(DBRequest::DB_ENTRY_ADD_CHANGE);
        req.key.reset(new InetUnicastRouteKey(vm_intf->peer(),
            intf_vrf->GetName(), ll_ip, 128));
        req.data.reset(data);

        intf_inet_table->Process(req);
    }

    // Announce a route to return from vhost vrf to the ll_ip vrf
    if (vhost_vrf == NULL)
        return;
    {
        InetUnicastAgentRouteTable *vhost_inet_table =
            vhost_vrf->GetInetUnicastRouteTable(ll_ip);
        if (vhost_inet_table == NULL)
            return;

        DBRequest nh_req_vrf(DBRequest::DB_ENTRY_ADD_CHANGE);
        nh_req_vrf.key.reset(new VrfNHKey(intf_vrf->GetName(), false, false));
        nh_req_vrf.data.reset(new VrfNHData(false, false, false));

        EcmpLoadBalance ecmp_load_balance;
        PathPreference path_preference;
        VnListType vn_list;

        vhost_inet_table->AddEvpnRoutingRoute(
            ll_ip,  // route to U
            128,
            intf_vrf,
            vm_intf->agent()->evpn_routing_peer(),
            SecurityGroupList(),
            CommunityList(),
            path_preference,
            ecmp_load_balance,
            TagList(),
            nh_req_vrf,  // nh_req_intf,
            intf_vrf->vxlan_id(),
            vn_list);
    }

    ll_ipv6_addresses_.insert(std::make_pair(vm_intf->name(), ll_ip));

    // Create neighbours records (ip neigh add ...)
    this->NetlinkAddVhostNb(ll_ip, vm_intf->vm_mac());
}

void MetadataProxy::DeleteMetaDataLinkLocalRoute(const VmInterface* vm_intf) {
    if (vm_intf == NULL)
        return;
    tbb::mutex::scoped_lock lock(ll_ipv6_addr_mutex_);
    Ip6Address ll_ip = Ip6Address::from_string(std::string("::"));
    if (!ll_ipv6_addresses_.count(vm_intf->name()))
        return;

    ll_ip = ll_ipv6_addresses_.at(vm_intf->name());
    const VrfEntry *vrf_entry = services_->agent()->
        vrf_table()->FindVrfFromName(vm_intf->vrf_name());
    if (!vrf_entry)
        return;

    if (services_->agent()->interface_table()) {
        services_->agent()->interface_table()->
            UnlinkVmPortFromMetaDataIp(vm_intf, ll_ip);
    }

    DBEntryBase::KeyPtr tintf_key_ptr;
    InetUnicastRouteEntry *c_entry = NULL;

    tintf_key_ptr = vm_intf->GetDBRequestKey();
    const VmInterfaceKey* intf_key_ptr =
        dynamic_cast<const VmInterfaceKey *>(tintf_key_ptr.get());
    if (!intf_key_ptr)
        return;

    c_entry = vrf_entry->GetUcRoute(ll_ip);
    if (!c_entry)
        return;

    {
        InetUnicastAgentRouteTable *fabric_inet =
            services_->agent()->fabric_vrf()->
                GetInet6UnicastRouteTable();
            fabric_inet->Delete(services_->agent()->evpn_routing_peer(),
                services_->agent()->fabric_vrf_name(), ll_ip, 128);
    }
    {
        VnListType vn_list;
        if (vm_intf->vn())
            vn_list.insert(vm_intf->vn()->GetName());
        InetInterfaceKey intf_key(vm_intf->name());
        // InetInterfaceRoute *data = new InetInterfaceRoute
        //     (intf_key, vm_intf->label(), local_path->GetTunnelType(),
        //     local_path->dest_vn_list(), local_path->sequence());
        InetInterfaceRoute *data = new InetInterfaceRoute
            (intf_key, vm_intf->label(), TunnelType::MplsType(),
            vn_list, vm_intf->peer()->sequence_number());

        InetUnicastAgentRouteTable *table =
            vrf_entry->GetInet6UnicastRouteTable();
        if (table) {
            table->Delete(
                vm_intf->peer(),
                vrf_entry->GetName(),
                ll_ip, c_entry->plen(),
                data);
        }
    }

    if (ll_ipv6_addresses_.count(vm_intf->name())) {
        ll_ipv6_addresses_.erase(vm_intf->name());
    }
}

const Ip6Address& MetadataProxy::Ipv6ServiceAddress() const {
    return ipv6_service_address_;
}

void MetadataProxy::ResetIp6Server
(const Ip6Address& new_ip, const int new_port) {
    if (http_server6_ == NULL)
        return;
    const int old_port = http_server6_->GetPort();
    if (new_port - old_port || new_ip != Ipv6ServiceAddress()) {
        const int vhost_idx =  VhostIndex(
            this->services_->agent()->vhost_interface_name());
         http_server6_->WaitForEmpty();
        // Delete server
        http_server6_->Shutdown();
        TcpServerManager::DeleteServer(http_server6_);
        http_server6_ = NULL;
        // Start server again
        if (Ipv6ServiceAddress() != new_ip &&
            Ipv6ServiceAddress() != Ip6Address()) {
            // Delete old address
            this->DeleteVhostRoutes();
            this->NetlinkDelVhostIp(Ipv6ServiceAddress());
        }
        this->NetlinkAddVhostIp(new_ip);
        ipv6_service_address_ = new_ip;
        http_server6_ = new MetadataServer(services_->agent()->event_manager());
        http_server6_->RegisterHandler(HTTP_WILDCARD_ENTRY,
            boost::bind(&MetadataProxy::HandleMetadataRequest, this, _1, _2));
        http_server6_->Initialize(new_port, Ipv6ServiceAddress(), vhost_idx);
        this->AnnounceVhostRoutes();
    }
}

void MetadataProxy::OnAVrfChange(DBTablePartBase *, DBEntryBase * entry) {
    tbb::mutex::scoped_lock lock(mutex_);
    VrfEntry *vrf_entry = dynamic_cast<VrfEntry*>(entry);

    // a new entry or a changed entry
    if (vrf_entry && !vrf_entry->IsDeleted()) {
        // Register event handler for 169.254.169.254 route change
        if (fabric_policy_notify_id_ < 0) {
            if (vrf_entry->GetName() == services_->agent()->
                fabric_policy_vrf_name()) {
                InetUnicastAgentRouteTable *fabric_policy_inet4_table =
                    vrf_entry->GetInet4UnicastRouteTable();
                if (fabric_policy_inet4_table) {
                    fabric_policy_notify_id_ =
                        fabric_policy_inet4_table->Register(
                            boost::bind(
                                &MetadataProxy::OnAFabricPolicyRouteChange,
                                this, _1, _2));
                }
            }
        }
        this->AnnounceVhostRoute(vrf_entry);
    }
    if (vrf_entry && vrf_entry->IsDeleted()) {
        this->DeleteVhostRoute(vrf_entry);
    }
}

void MetadataProxy::OnAFabricPolicyRouteChange
    (DBTablePartBase *, DBEntryBase *entry) {
    if (entry->IsDeleted())
        return;

    tbb::mutex::scoped_lock lock(mutex_);
    InetUnicastAgentRouteTable *inet_table =
       dynamic_cast<InetUnicastAgentRouteTable*>(entry->get_table());
    if (!inet_table)
        return;

    InetUnicastRouteEntry *route_entry =
        dynamic_cast<InetUnicastRouteEntry*>(entry);
    if (!route_entry)
        return;

    // find a metadata service
    std::set<std::string> metadata_service_names;
    const Ip4Address serv_ip = route_entry->addr().to_v4();
    uint16_t nova_port, linklocal_port;
    Ip4Address nova_server, linklocal_server;
    std::string nova_hostname;

    if (services_->agent()->oper_db()->global_vrouter()->FindLinkLocalService(
        GlobalVrouter::kMetadataService, &linklocal_server, &linklocal_port,
        &nova_hostname, &nova_server, &nova_port)) {
        if (linklocal_server == serv_ip) {
            boost::asio::ip::address_v6::bytes_type serv_ip6_bytes =
                {0xFE, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00};
            boost::asio::ip::address_v4::bytes_type serv_ip4_bytes =
                serv_ip.to_bytes();
            serv_ip6_bytes[15] = serv_ip4_bytes[3];
            serv_ip6_bytes[14] = serv_ip4_bytes[2];
            serv_ip6_bytes[13] = serv_ip4_bytes[1];
            serv_ip6_bytes[12] = serv_ip4_bytes[0];
            Ip6Address serv_ip6(serv_ip6_bytes);
            this->ResetIp6Server(serv_ip6, linklocal_port);
        }
    }
}

void MetadataProxy::OnAnInterfaceChange(DBTablePartBase *, DBEntryBase *entry) {
    VmInterface *vmi = dynamic_cast<VmInterface *>(entry);
    if (!vmi)
        return;

    if (vmi->IsDeleted() && vmi != services_->agent()->vhost_interface()) {
        DeleteMetaDataLinkLocalRoute(vmi);
    }
}

void MetadataProxy::RegisterListeners() {
    vrf_table_notify_id_     = -1;
    intf_table_notify_id_    = -1;
    fabric_policy_notify_id_ = -1;  // Will be registered later,
                                    // since the table isn't present now
    if (services_->agent()->vrf_table()) {
        vrf_table_notify_id_ =
            services_->agent()->vrf_table()->Register(
                boost::bind(&MetadataProxy::OnAVrfChange, this, _1, _2));
    }
    if (services_->agent()->interface_table()) {
        intf_table_notify_id_ =
            services_->agent()->interface_table()->Register(
                boost::bind(&MetadataProxy::OnAnInterfaceChange, this, _1, _2));
    }
}

void MetadataProxy::UnregisterListeners() {
    if (vrf_table_notify_id_ > -1) {
        services_->agent()->vrf_table()->
            Unregister(vrf_table_notify_id_);
        vrf_table_notify_id_ = -1;
    }
    if (intf_table_notify_id_ > -1) {
        services_->agent()->interface_table()->
            Unregister(intf_table_notify_id_);
        intf_table_notify_id_ = -1;
    }
    if (fabric_policy_notify_id_ > -1) {
        services_->agent()->fabric_policy_vrf()->
            GetInet4UnicastRouteTable()->
            Unregister(fabric_policy_notify_id_);
        fabric_policy_notify_id_ = -1;
    }
}

//
// END-OF-FILE
//
