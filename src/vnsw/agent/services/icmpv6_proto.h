/*
 * Copyright (c) 2014 Juniper Networks, Inc. All rights reserved.
 */

#ifndef vnsw_agent_icmpv6_proto_h
#define vnsw_agent_icmpv6_proto_h

#include "pkt/proto.h"
#include "services/icmpv6_handler.h"
#include "services/ndp_entry.h"

#define ICMP_PKT_SIZE 1024
#define IPV6_ALL_NODES_ADDRESS "FF02::1"
#define IPV6_ALL_ROUTERS_ADDRESS "FF02::2"
#define PKT0_LINKLOCAL_ADDRESS "FE80::5E00:0100"

#define NDP_TRACE(obj, ...)                                                 \
do {                                                                        \
    Ndp##obj::TraceMsg(Icmpv6TraceBuf, __FILE__, __LINE__, ##__VA_ARGS__);     \
} while (false)                                                             \

/*#define NDP_LOG(obj, ...)                                                 \
do {                                                                        \
    Ndp##obj::TraceMsg(NdpTraceBuf, __FILE__, __LINE__, ##__VA_ARGS__);     \
} while (false)                                                             \
*/
#define ICMPV6_TRACE(obj, arg)                                               \
do {                                                                         \
    std::ostringstream _str;                                                 \
    _str << arg;                                                             \
    Icmpv6##obj::TraceMsg(Icmpv6TraceBuf, __FILE__, __LINE__, _str.str());   \
} while (false)                                                              \

class Icmpv6VrfState;
class Icmpv6PathPreferenceState;

class Icmpv6Proto : public Proto {
public:
    static const uint32_t kRouterAdvertTimeout = 30000; // milli seconds
    static const uint16_t kMaxRetries = 8;
    static const uint32_t kRetryTimeout = 2000;            // milli seconds
    static const uint32_t kAgingTimeout = (5 * 60 * 1000); // milli seconds

    enum Icmpv6MsgType {
        NDP_RESOLVE,
        NDP_DELETE,
        AGING_TIMER_EXPIRED,
        NDP_SEND_UNSOL_NA,
    };

    struct Icmpv6Ipc : InterTaskMsg {
        Icmpv6Ipc(Icmpv6Proto::Icmpv6MsgType msg, NdpKey &akey, InterfaceConstRef itf)
            : InterTaskMsg(msg), key(akey), interface_(itf) {}
        Icmpv6Ipc(Icmpv6Proto::Icmpv6MsgType msg, Ip6Address ip,
                  const VrfEntry *vrf, InterfaceConstRef itf) :
            InterTaskMsg(msg), key(ip, vrf), interface_(itf) {}

        NdpKey key;
        InterfaceConstRef interface_;
    };

    struct Icmpv6Stats {
        Icmpv6Stats() { Reset(); }
        void Reset() {
            icmpv6_router_solicit_ = icmpv6_router_advert_ = 0;
            icmpv6_ping_request_ = icmpv6_ping_response_ = icmpv6_drop_ = 0;
            icmpv6_neighbor_solicit_ = icmpv6_neighbor_advert_solicited_ = 0;
            icmpv6_neighbor_solicited_ = 0;
            icmpv6_neighbor_advert_unsolicited_ = 0;
        }

        uint32_t icmpv6_router_solicit_;
        uint32_t icmpv6_router_advert_;
        uint32_t icmpv6_ping_request_;
        uint32_t icmpv6_ping_response_;
        uint32_t icmpv6_drop_;
        uint32_t icmpv6_neighbor_solicit_;
        uint32_t icmpv6_neighbor_solicited_;
        uint32_t icmpv6_neighbor_advert_solicited_;
        uint32_t icmpv6_neighbor_advert_unsolicited_;
    };

    typedef std::map<VmInterface *, Icmpv6Stats> VmInterfaceMap;
    typedef std::pair<VmInterface *, Icmpv6Stats> VmInterfacePair;
    typedef std::map<NdpKey, NdpEntry *> NdpCache;
    typedef std::pair<NdpKey, NdpEntry *> NdpCachePair;
    typedef std::map<NdpKey, NdpEntry *>::iterator NdpIterator;
    typedef std::set<NdpKey> NdpKeySet;
    typedef std::set<NdpEntry *> NdpEntrySet;
    typedef std::map<NdpKey, NdpEntrySet> UnsolNaCache;
    typedef std::pair<NdpKey, NdpEntrySet> UnsolNaCachePair;
    typedef std::map<NdpKey, NdpEntrySet>::iterator UnsolNaIterator;

    struct InterfaceNdpInfo {
        InterfaceNdpInfo() : ndp_key_list(), stats() {}
        NdpKeySet ndp_key_list;
        Icmpv6Stats stats;
    };
    typedef std::map<uint32_t, InterfaceNdpInfo> InterfaceNdpMap;
    typedef std::pair<uint32_t, InterfaceNdpInfo> InterfaceNdpPair;

    void Shutdown();
    Icmpv6Proto(Agent *agent, boost::asio::io_service &io);
    virtual ~Icmpv6Proto();
    ProtoHandler *AllocProtoHandler(boost::shared_ptr<PktInfo> info,
                                    boost::asio::io_service &io);
    void VrfNotify(DBTablePartBase *part, DBEntryBase *entry);
    void VnNotify(DBEntryBase *entry);
    void InterfaceNotify(DBEntryBase *entry);
    void NexthopNotify(DBEntryBase *entry);
    void SendIcmpv6Ipc(Icmpv6Proto::Icmpv6MsgType type, Ip6Address ip,
                       const VrfEntry *vrf, InterfaceConstRef itf);

    const VmInterfaceMap &vm_interfaces() { return vm_interfaces_; }

    void IncrementStatsRouterSolicit(VmInterface *vmi);
    void IncrementStatsRouterAdvert(VmInterface *vmi);
    void IncrementStatsPingRequest(VmInterface *vmi);
    void IncrementStatsPingResponse(VmInterface *vmi);
    void IncrementStatsDrop() { stats_.icmpv6_drop_++; }
    void IncrementStatsNeighborAdvertSolicited(VmInterface *vmi);
    void IncrementStatsNeighborAdvertUnSolicited(VmInterface *vmi);
    void IncrementStatsNeighborSolicit(VmInterface *vmi);
    void IncrementStatsNeighborSolicited(VmInterface *vmi);
    const Icmpv6Stats &GetStats() const { return stats_; }
    Icmpv6Stats *VmiToIcmpv6Stats(VmInterface *i);
    void ClearStats() { stats_.Reset(); }
    bool ValidateAndClearVrfState(VrfEntry *vrf, Icmpv6VrfState *state);
    Icmpv6VrfState *CreateAndSetVrfState(VrfEntry *vrf);

    Interface *ip_fabric_interface() const { return ip_fabric_interface_; }
    uint32_t ip_fabric_interface_index() const {
        return ip_fabric_interface_index_;
    }
    const MacAddress &ip_fabric_interface_mac() const {
        return ip_fabric_interface_mac_;
    }
    void set_ip_fabric_interface(Interface *itf) { ip_fabric_interface_ = itf; }
    void set_ip_fabric_interface_index(uint32_t ind) {
        ip_fabric_interface_index_ = ind;
    }
    void set_ip_fabric_interface_mac(const MacAddress &mac) {
        ip_fabric_interface_mac_ = mac;
    }

    bool AddNdpEntry(NdpEntry *entry);
    bool DeleteNdpEntry(NdpEntry *entry);
    NdpEntry *FindNdpEntry(const NdpKey &key);
    std::size_t GetNdpCacheSize() { return ndp_cache_.size(); }
    const NdpCache& ndp_cache() { return ndp_cache_; }
    const UnsolNaCache& unsol_na_cache() { return unsol_na_cache_; }
    const InterfaceNdpMap& interface_ndp_map() { return interface_ndp_map_; }

    void AddUnsolNaEntry(NdpKey &key);
    void DeleteUnsolNaEntry(NdpEntry *entry);
    NdpEntry* FindUnsolNaEntry(NdpKey &key);
    NdpEntry* UnsolNaEntry (const NdpKey &key, const Interface *intf);
    Icmpv6Proto::UnsolNaIterator
        UnsolNaEntryIterator(const NdpKey &key, bool *key_valid);
    DBTableBase::ListenerId vrf_table_listener_id() const {
        return vrf_table_listener_id_;
    }

private:
    Timer *timer_;
    Icmpv6Stats stats_;
    VmInterfaceMap vm_interfaces_;
    NdpCache ndp_cache_;
    UnsolNaCache unsol_na_cache_;
    InterfaceNdpMap interface_ndp_map_;
    bool HandlePacket();
    bool HandleMessage();
    Icmpv6Proto::NdpIterator DeleteNdpEntry(Icmpv6Proto::NdpIterator iter);
    void SendIcmpv6Ipc(Icmpv6Proto::Icmpv6MsgType type, NdpKey &key,
                       InterfaceConstRef itf);
    // handler to send router advertisements and neighbor solicits
    boost::scoped_ptr<Icmpv6Handler> icmpv6_handler_;
    DBTableBase::ListenerId vn_table_listener_id_;
    DBTableBase::ListenerId vrf_table_listener_id_;
    DBTableBase::ListenerId interface_listener_id_;
    DBTableBase::ListenerId nexthop_listener_id_;
    uint32_t ip_fabric_interface_index_;
    MacAddress ip_fabric_interface_mac_;
    Interface *ip_fabric_interface_;
    DISALLOW_COPY_AND_ASSIGN(Icmpv6Proto);
};

class Icmpv6VrfState : public DBState {
public:
    typedef std::map<const IpAddress,
                     Icmpv6PathPreferenceState*> Icmpv6PathPreferenceStateMap;
    typedef std::pair<const IpAddress,
                     Icmpv6PathPreferenceState*> Icmpv6PathPreferenceStatePair;

    Icmpv6VrfState(Agent *agent, Icmpv6Proto *proto, VrfEntry *vrf,
                   AgentRouteTable *table, AgentRouteTable *evpn_table);
    ~Icmpv6VrfState();
    Agent *agent() const { return agent_; }
    Icmpv6Proto * icmp_proto() const { return icmp_proto_; }
    void set_route_table_listener_id(const DBTableBase::ListenerId &id) {
        route_table_listener_id_ = id;
    }
    void set_evpn_route_table_listener_id(const DBTableBase::ListenerId &id) {
        evpn_route_table_listener_id_ = id;
    }
    bool default_routes_added() const { return default_routes_added_; }
    void set_default_routes_added(bool value) { default_routes_added_ = value; }

    void RouteUpdate(DBTablePartBase *part, DBEntryBase *entry);
    void EvpnRouteUpdate(DBTablePartBase *part, DBEntryBase *entry);
    void ManagedDelete() { deleted_ = true;}
    void Delete();
    bool DeleteRouteState(DBTablePartBase *part, DBEntryBase *entry);
    bool DeleteEvpnRouteState(DBTablePartBase *part, DBEntryBase *entry);
    bool PreWalkDone(DBTableBase *partition);
    static void WalkDone(DBTableBase *partition, Icmpv6VrfState *state);
    bool deleted() const {return deleted_;}

    Icmpv6PathPreferenceState* Locate(const IpAddress &ip);
    void Erase(const IpAddress &ip);
    Icmpv6PathPreferenceState* Get(const IpAddress ip) {
        return icmpv6_path_preference_map_[ip];
    }

    bool l3_walk_completed() const {
        return l3_walk_completed_;
    }

    bool evpn_walk_completed() const {
        return evpn_walk_completed_;
    }
    DBTable::DBTableWalkRef managed_delete_walk_ref() {
        return managed_delete_walk_ref_;
    }
    DBTable::DBTableWalkRef evpn_walk_ref() {
        return evpn_walk_ref_;
    }

private:
    Agent *agent_;
    Icmpv6Proto *icmp_proto_;
    VrfEntry *vrf_;
    AgentRouteTable *rt_table_;
    AgentRouteTable *evpn_rt_table_;
    DBTableBase::ListenerId route_table_listener_id_;
    DBTableBase::ListenerId evpn_route_table_listener_id_;
    LifetimeRef<Icmpv6VrfState> table_delete_ref_;
    LifetimeRef<Icmpv6VrfState> evpn_table_delete_ref_;
    bool deleted_;
    bool default_routes_added_;
    DBTable::DBTableWalkRef managed_delete_walk_ref_;
    DBTable::DBTableWalkRef evpn_walk_ref_;
    Icmpv6PathPreferenceStateMap icmpv6_path_preference_map_;
    bool l3_walk_completed_;
    bool evpn_walk_completed_;
    DISALLOW_COPY_AND_ASSIGN(Icmpv6VrfState);
};

class Icmpv6PathPreferenceState {
public:
    static const uint32_t kMaxRetry = 30 * 5; //retries upto 5 minutes,
                                              //30 tries/per minutes
    static const uint32_t kTimeout = 2000;

    static const uint32_t kTimeoutMultiplier = 5;

    typedef std::map<uint32_t, uint32_t> WaitForTrafficIntfMap;
    typedef std::set<uint32_t> NDTransmittedIntfMap;

    Icmpv6PathPreferenceState(Icmpv6VrfState *vrf_state, uint32_t vrf_id,
                              IpAddress vm_ip_addr, uint8_t plen);
    ~Icmpv6PathPreferenceState();
    bool SendNeighborSolicit();
    bool SendNeighborSolicit(WaitForTrafficIntfMap &wait_for_traffic_map,
                            NDTransmittedIntfMap &nd_transmitted_map);
    void SendNeighborSolicitForAllIntf(const AgentRoute *route);
    void StartTimer();

    Icmpv6VrfState* vrf_state() {
        return vrf_state_;
    }

    const IpAddress& ip() const {
        return vm_ip_;
    }

    bool IntfPresentInIpMap(uint32_t id) {
        if (l3_wait_for_traffic_map_.find(id) ==
                l3_wait_for_traffic_map_.end()) {
            return false;
        }
        return true;
    }

    bool IntfPresentInEvpnMap(uint32_t id) {
        if (evpn_wait_for_traffic_map_.find(id) ==
                evpn_wait_for_traffic_map_.end()) {
            return false;
        }
        return true;
    }

    uint32_t IntfRetryCountInIpMap(uint32_t id) {
        return l3_wait_for_traffic_map_[id];
    }

    uint32_t IntfRetryCountInEvpnMap(uint32_t id) {
        return evpn_wait_for_traffic_map_[id];
    }

private:
    friend void intrusive_ptr_add_ref(Icmpv6PathPreferenceState *ps);
    friend void intrusive_ptr_release(Icmpv6PathPreferenceState *ps);
    Icmpv6VrfState *vrf_state_;
    Timer *ns_req_timer_;
    uint32_t vrf_id_;
    IpAddress vm_ip_;
    uint8_t plen_;
    IpAddress svc_ip_;
    WaitForTrafficIntfMap l3_wait_for_traffic_map_;
    WaitForTrafficIntfMap evpn_wait_for_traffic_map_;
    tbb::atomic<int> refcount_;
};

typedef boost::intrusive_ptr<Icmpv6PathPreferenceState>
            Icmpv6PathPreferenceStatePtr;

void intrusive_ptr_add_ref(Icmpv6PathPreferenceState *ps);
void intrusive_ptr_release(Icmpv6PathPreferenceState *ps);

class Icmpv6RouteState : public DBState {
public:
    Icmpv6RouteState(Icmpv6VrfState *vrf_state, uint32_t vrf_id,
                     IpAddress vm_ip_addr, uint8_t plen);
    ~Icmpv6RouteState();
    void SendNeighborSolicitForAllIntf(const AgentRoute *route);
private:
    Icmpv6PathPreferenceStatePtr icmpv6_path_preference_state_;
};
#endif // vnsw_agent_icmpv6_proto_h
