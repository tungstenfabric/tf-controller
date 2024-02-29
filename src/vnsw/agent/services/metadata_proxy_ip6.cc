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
#include <oper/vxlan_routing_manager.h>
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

void MetadataProxy::AdvertiseMetaDataLinkLocalRoutes(const VmInterface* vm_intf,
    const Ip6Address& ll_ip, const VrfEntry* intf_vrf) {
    if (vm_intf == NULL || intf_vrf == NULL) {
        return;
    }

    tbb::mutex::scoped_lock lock(ll_ipv6_addr_mutex_);
    {
        InetUnicastAgentRouteTable *intf_inet_table =
            intf_vrf->GetInet6UnicastRouteTable();
        if (intf_inet_table == NULL)
            return;
        InetUnicastRouteEntry* rt_entry =
            intf_inet_table->FindRoute(ll_ip);
        // explicitly forbid advertisement of LL IPv6 route
        // if another with the given prefix exists
        if (rt_entry != NULL &&
            rt_entry->addr().to_v6() == ll_ip &&
            rt_entry->plen() == 128) {
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

    ll_ipv6_addresses_.insert(std::make_pair(vm_intf->name(), ll_ip));
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

void MetadataProxy::InitializeHttp6Server(const VmInterface *vhost0) {
    if (vhost0 == NULL ||
        vhost0->mdata_ip6_addr().is_unspecified() ||
        !vhost0->mdata_ip6_addr().is_link_local() ||
        !ipv6_service_address_.is_unspecified()) {
        return;
    }
    ipv6_service_address_ = vhost0->mdata_ip6_addr();
    if (!NetlinkAddVhostIp(ipv6_service_address_)) {
        LOG(ERROR, "An error has occured during binding IPv6 ll"
        " address to vhost0 in"
        " MetadataProxy::InitializeHttp6Server");
        return;
    }
    const int vhost_idx =  VhostIndex(
        this->services_->agent()->vhost_interface_name());
    http_server6_->RegisterHandler(HTTP_WILDCARD_ENTRY,
        boost::bind(&MetadataProxy::HandleMetadataRequest, this, _1, _2));
    http_server6_->Initialize(
        services_->agent()->metadata_server_port(),
        ipv6_service_address_, vhost_idx);
}

void MetadataProxy::OnAVrfChange(DBTablePartBase *, DBEntryBase * entry) {

    VrfEntry *vrf_entry = dynamic_cast<VrfEntry*>(entry);

    // a new entry or a changed entry
    if (vrf_entry && !vrf_entry->IsDeleted()) {
        if (fabric_notify_id_ < 0) {
            if (vrf_entry == services_->agent()->fabric_vrf()) {
                InetUnicastAgentRouteTable *fabric_inet6_table =
                    vrf_entry->GetInet6UnicastRouteTable();
                if (fabric_inet6_table) {
                    fabric_notify_id_ =
                        fabric_inet6_table->Register(
                            boost::bind(
                                &MetadataProxy::OnAFabricRouteChange,
                                this, _1, _2));
                }
            }
        }
        // this->AdvertiseVhostRoute(vrf_entry);
    }
}

void MetadataProxy::OnAFabricRouteChange
    (DBTablePartBase *, DBEntryBase *entry) {

    InetUnicastAgentRouteTable *inet_table =
       dynamic_cast<InetUnicastAgentRouteTable*>(entry->get_table());
    if (!inet_table)
        return;

    InetUnicastRouteEntry *route_entry =
        dynamic_cast<InetUnicastRouteEntry*>(entry);
    if (!route_entry)
        return;

    const AgentPath *active_path = route_entry->GetActivePath();
    const NextHop *active_nh = active_path ? active_path->nexthop() : NULL;
    const InterfaceNH *interface_nh =
        dynamic_cast<const InterfaceNH*>(active_nh);
    if (interface_nh == NULL) {
        return;
    }

    const VmInterface *interface = dynamic_cast<const VmInterface*>(
        interface_nh->GetInterface());
    if (interface == NULL) {
        return;
    }
    const Ip6Address mip6 = interface->mdata_ip6_addr();

    if (mip6 == route_entry->addr().to_v6()) {
        if (entry->IsDeleted()) {
        } else {
            // Create neighbours records (ip neigh add ...)
            this->NetlinkAddVhostNb(mip6, interface->vm_mac());
        }
    }
}

void MetadataProxy::OnAnInterfaceChange(DBTablePartBase *, DBEntryBase *entry) {
    VmInterface *vmi = dynamic_cast<VmInterface *>(entry);
    if (!vmi)
        return;

    if (vmi->IsDeleted() && vmi != services_->agent()->vhost_interface()) {
        DeleteMetaDataLinkLocalRoute(vmi);
        return;
    }

    if (!vmi->IsDeleted() && vmi == services_->agent()->vhost_interface()) {
        InitializeHttp6Server(vmi);
    }

    if (vmi->IsDeleted() &&
        vmi->name() == services_->agent()->vhost_interface_name()) {
        NetlinkDelVhostIp(vmi->mdata_ip6_addr());
        return;
    }
}

void MetadataProxy::RegisterListeners() {
    vrf_table_notify_id_     = -1;
    intf_table_notify_id_    = -1;
    fabric_notify_id_        = -1;  // Will be registered later,
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
    if (fabric_notify_id_ > -1) {
        services_->agent()->fabric_vrf()->
            GetInet6UnicastRouteTable()->
            Unregister(fabric_notify_id_);
        fabric_notify_id_ = -1;
    }
}

//
// END-OF-FILE
//
