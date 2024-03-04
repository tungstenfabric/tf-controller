/*
 * Copyright (c) 2018 Juniper Networks, Inc. All rights reserved.
 */

#ifndef __AGENT_OPER_VXLAN_ROUTING_H
#define __AGENT_OPER_VXLAN_ROUTING_H

#include <cmn/agent_cmn.h>
#include <cmn/agent.h>
#include <oper/oper_db.h>
#include <base/logging.h>

class BgpPeer;
namespace autogen {
    struct EnetNextHopType;
    struct NextHopType;
}


/// @brief A structure to hold path parameters during
/// the transfer (routes leaking) of data between VRF instances and tables.
/// The structure is designed to use references where it is possible.
struct RouteParameters {

    /// @brief Constructs RouteParameters object from components
    RouteParameters(const IpAddress& nh_addr,
        const MacAddress& mac,
        const VnListType& vns,
        const SecurityGroupList& sgs,
        const CommunityList& comms,
        const TagList& tags,
        const PathPreference& ppref,
        const EcmpLoadBalance& ecmp,
        uint64_t seq_n):
        nh_addresses_(1, nh_addr),
        nh_addr_(nh_addresses_.at(0)),
        nh_mac_(mac),
        vn_list_(vns), sg_list_(sgs),
        communities_(comms), tag_list_(tags),
        path_preference_(ppref),
        ecmp_load_balance_(ecmp),
        sequence_number_(seq_n) {
    }

    /// @brief Copy constructor
    RouteParameters(const RouteParameters &rp):
        nh_addresses_(rp.nh_addresses_),
        nh_addr_(rp.nh_addr_),
        nh_mac_(rp.nh_mac_),
        vn_list_(rp.vn_list_), sg_list_(rp.sg_list_),
        communities_(rp.communities_), tag_list_(rp.tag_list_),
        path_preference_(rp.path_preference_),
        ecmp_load_balance_(rp.ecmp_load_balance_),
        sequence_number_(rp.sequence_number_) {
    }

    // template <class ITEM_T
    // static std::vector<typename ITEM_T> ItemToVector(const ITEM_T& item) {
    //     return std::vector<ITEM_T>();
    // }

    // template<class ITEM_T>
    // RouteParameters(const ITEM_T& item,
    //     const VnListType& vns,
    //     const SecurityGroupList& sgs,
    //     const TagList& tags,
    //     const PathPreference& ppref,
    //     const EcmpLoadBalance& ecmp,
    //     uint64_t seq_n):
    //     nh_addr_(nh_addr),
    //     vn_list_(vns), sg_list_(sgs),
    //     tag_list_(tags), path_preference_(ppref),
    //     ecmp_load_balance_(ecmp),
    //     sequence_number_(seq_n) {
    // }

    /// @brief A list of nexthops IP addreses of a composite tunnel.
    const std::vector<IpAddress> nh_addresses_;

    /// @brief A nexthop IP address of the tunnel. Contains first IP address
    /// of nh_addresses_ in case of a composite tunnel.
    const IpAddress& nh_addr_;

    /// @brief A nexthop MAC address (usually it is a MAC of the router).
    const MacAddress& nh_mac_;

    /// @brief A list of path destination virtual networks used in policy
    /// lookups.
    const VnListType& vn_list_;

    /// @brief A list of security groups.
    const SecurityGroupList& sg_list_;

    /// @brief A list of communities.
    const CommunityList& communities_;

    /// @brief A list of tags.
    const TagList& tag_list_;

    /// @brief A reference to the PathPreference of the path
    const PathPreference& path_preference_;

    /// @brief A reference to EcmpLoadBalance of the path
    const EcmpLoadBalance& ecmp_load_balance_;

    /// @brief An ID of sequence
    uint64_t sequence_number_;

private:

    /// @brief Disallow default constructor
    RouteParameters();
};

/// @brief This state tracks inet and evpn table listeners.
/// The state establishes link between Inet tables of a bridge VRF instance
/// from where routes leak and EVPN table of a routing VRF instance
/// to which routes leak.
struct VxlanRoutingState : public DBState {

    /// @brief Construct new instance using the given VxlanRoutingManager and
    /// VRF instance (VrfEntry).
    VxlanRoutingState(VxlanRoutingManager *mgr,
                      VrfEntry *vrf);

    /// @brief Destroys an instance.
    virtual ~VxlanRoutingState();

    /// @brief ID of a listener that tracks changes in the IPv4 Inet
    /// table of a bridge VRF instance
    DBTable::ListenerId inet4_id_;

    /// @brief ID of a listener that tracks changes in the IPv6 Inet
    /// table of a bridge VRF instance
    DBTable::ListenerId inet6_id_;

    /// @brief ID of a listener that tracks changes in the EVPN
    /// table of a routing VRF instance
    DBTable::ListenerId evpn_id_;

    /// @brief A pointer to the IPv4 Inet table of a bridge VRF instance
    AgentRouteTable *inet4_table_;

    /// @brief A pointer to the IPv6 Inet table of a bridge VRF instance
    AgentRouteTable *inet6_table_;

    /// @brief A pointer to the EVPN table of a routing VRF instance
    AgentRouteTable *evpn_table_;
};

/// @brief This state tracks all virtual machine interfaces (VmInterface)
/// attached to a Logical Router (LR). The state establishes link
/// between VmInterfaces connected to a LR as
/// router's ports on behalf of bridge virtual networks (VirtualNetwork).
struct VxlanRoutingVnState : public DBState {

    /// A typedef for a set of pointers to VmInterface.
    typedef std::set<const VmInterface *> VmiList;

    /// A typedef for the iterator of VxlanRoutingVnState::VmiList.
    typedef VmiList::iterator VmiListIter;

    /// Constructs new instance using VxlanRoutingManager.
    VxlanRoutingVnState(VxlanRoutingManager *mgr);

    /// @brief Destroys a VxlanRoutingVnState object.
    virtual ~VxlanRoutingVnState();

    /// @brief Adds a VmInterface (LR port) to a Logical Router and connects
    /// the given VirtualNetwork (to which the VmInterface belongs to) to the
    /// LR.
    void AddVmi(const VnEntry *vn, const VmInterface *vmi);

    /// @brief Deletes the VmInterface from set of connected interfaces
    ///  and disconnects the given VirtualNetwork from the Logical Router.
    void DeleteVmi(const VnEntry *vn, const VmInterface *vmi);

    /// @brief Returns the UUID of the Logical Router.
    boost::uuids::uuid logical_router_uuid() const;

    /// @brief A list of VmInterface (router's ports) connected to a Logical
    /// Router (LR)
    std::set<const VmInterface *> vmi_list_;

    /// @brief Returns true when state is associated with a routing
    /// VirtualNetwork
    bool is_routing_vn_;

    /// @brief A  UUID of the Logical Router.
    boost::uuids::uuid logical_router_uuid_;

    /// @brief Holds a reference to a VrfEntry when VirtualNetwork's
    /// reference stored in VrfGet() is null
    VrfEntryRef vrf_ref_;

    /// @brief A pointer to the instance of VxlanRoutingManager
    VxlanRoutingManager *mgr_;
};

/// @brief Tracks movement of a VmInterface amongth LRs. This is used
/// to associate VmInterface with a LR and a VN;
struct VxlanRoutingVmiState : public DBState {

    /// @brief Constructs new instance of VxlanRoutingVmiState
    VxlanRoutingVmiState();

    /// @brief Destroys an instance of VxlanRoutingVmiState
    virtual ~VxlanRoutingVmiState();

    /// @brief Reference (smart pointer) to the virtual network
    /// (VirtualNetwork) to which VmInterface belongs to
    VnEntryRef vn_entry_;

    /// @brief UUID of the LR to which this VmInterface is connected.
    boost::uuids::uuid logical_router_uuid_;
};

/**
 * VxlanRoutingRouteWalker
 * Incarnation of AgentRouteWalker. 
 * 
 */
/// @brief Listens to Inet routes in a bridge VRF instance.
/// Started when l3vrf is added/deleted or
/// when a bridge VRF is attached / detached to/from the LR.
class VxlanRoutingRouteWalker : public AgentRouteWalker {
public:

    /// @brief Constructs a new instance using the given name, pointer to
    /// the VxlanRoutingManager and pointer to the Agent.
    VxlanRoutingRouteWalker(const std::string &name,
        VxlanRoutingManager *mgr, Agent *agent);

    /// @brief Destructs an instance of VxlanRoutingRouteWalker.
    virtual ~VxlanRoutingRouteWalker();

    /// @brief Runs route leaking process when L3 VRF instance is added/deleted
    /// or when a bridge VRF is attached / detached to/from the LR
    virtual bool RouteWalkNotify(DBTablePartBase *partition, DBEntryBase *e);

private:

    /// @brief A pointer to the VxlanRoutingManager instance.
    VxlanRoutingManager *mgr_;

    DISALLOW_COPY_AND_ASSIGN(VxlanRoutingRouteWalker);
};


/// @brief The class is used to store following information:
/// - VN to LR uuid mapping
/// - LR to RoutedVrfInfo mapping.
/// RoutedVrfInfo - Contains l3vrf as routing vrf and list of all bridge vrf
/// linked to this routing vrf.
/// Along with these it has a walker for walking evpn tables.
/// EVPN walk is triggered for following reasons:
/// - detection of l3vrf, walks all bridge evpn linked to same.
/// - bridge vrf addition - Here evpn table of this bridge vrf is walked.
/// - deletion of vrf
/// (If multiple walks get scheduled for evpn table then they are collapsed and
/// only one walk is done)
class VxlanRoutingVrfMapper {
public:

    /// @brief The structure holds information about virtual networks
    /// connected to a logical router (LR)
    struct RoutedVrfInfo {

        /// @brief A typedef to store the list of bridge virtual networks
        /// connected to a LR.
        typedef std::set<const VnEntry *> BridgeVnList;

        /// @brief A typedef to store the correspondence between bridge virtual
        /// network (VirtualNetwork) pointer and a name of it's VRF instance.
        typedef std::map<const VnEntry *, std::string> BridgeVrfNamesList;

        /// @brief A type for iterator of the list of bridge virtual networks
        /// connected to a LR.
        typedef BridgeVnList::iterator BridgeVnListIter;

        /// @brief Constructs an instance of RoutedVrfInfo.
        RoutedVrfInfo() : routing_vn_(),
        routing_vrf_(NULL), bridge_vn_list_() {
        }

        /// @brief Destroys an instance of RoutedVrfInfo.
        virtual ~RoutedVrfInfo() {
        }

        /// @brief A pointer to the routing virtual network (VirtualNetwork)
        /// connected to a LR.
        const VnEntry *routing_vn_;

        /// @brief A pointer to the routing VRF instance (L3 VRF)
        /// connected to a LR.
        const VrfEntry *routing_vrf_;

        /// @brief The list of bridge virtual networks (VirtualNetwork)
        /// connected to a LR.
        BridgeVnList bridge_vn_list_;

        /// @brief The list of bridge virtual networks (VirtualNetwork) names
        /// connected to a LR.
        BridgeVrfNamesList bridge_vrf_names_list_;
    };

    /// @brief A typedef to store map between Logical router UUID and
    /// RoutedVrfInfo
    typedef std::map<boost::uuids::uuid, RoutedVrfInfo> LrVrfInfoMap;

    /// @brief A typedef for iterator of LrVrfInfoMap
    typedef LrVrfInfoMap::iterator LrVrfInfoMapIter;

    /// @brief A typedef to store map between pointer to VirtualNetwork (a
    /// bridge or routing virtual network connected to some LR) and
    /// the LR's UUID.
    typedef std::map<const VnEntry *, boost::uuids::uuid> VnLrSet;

    /// @brief A typedef for iterator of VnLrSet.
    typedef VnLrSet::iterator VnLrSetIter;

    /// @brief A typedef for a storage of all walkers on Inet tables,
    /// if needed the walk can be restarted
    /// instead of spawning new one for a table.
    typedef std::map<const InetUnicastAgentRouteTable *, DBTable::DBTableWalkRef>
        InetTableWalker;

    /// @brief Constructs a new instance of VxlanRoutingVrfMapper using
    /// the given pointer to VxlanRoutingManager.
    VxlanRoutingVrfMapper(VxlanRoutingManager *mgr);

    /// @brief Destroys an instance of VxlanRoutingVrfMapper().
    virtual ~VxlanRoutingVrfMapper();

    /// @brief Handles completion of route walk in the Inet IPv4 table
    /// of a bridge VRF instance.
    void BridgeInet4RouteWalkDone(DBTable::DBTableWalkRef walk_ref,
                       DBTableBase *partition);

    /// @brief Handles completion of route walk in an Inet IPv6 table
    /// of a bridge VRF instance.
    void BridgeInet6RouteWalkDone(DBTable::DBTableWalkRef walk_ref,
                       DBTableBase *partition);

    /// @brief Handles completion of route walk in the EVPN table
    /// of a routing VRF instance.
    void RoutingVrfRouteWalkDone(DBTable::DBTableWalkRef walk_ref,
                                          DBTableBase *partition);

    /// @brief Attempts to delete the given LR.
    /// @todo better way to release logical router from lr_vrf_info_map_
    /// Easier way will be to add logical router in db and trigger delete of this
    ///via LR delete in same.
    void TryDeleteLogicalRouter(LrVrfInfoMapIter &it);

    /// @brief Determines whether object is empty or not.
    bool IsEmpty() const {
        return ((vn_lr_set_.size() == 0) &&
                (lr_vrf_info_map_.size() == 0));
    }

private:

    /// @brief Allows access to private members for VxlanRoutingManager class.
    friend class VxlanRoutingManager;

    /// @brief Walks Inet tables of all bridge VRF instances connected to
    /// a LR (given in routing_vrf_info parameter).
    void WalkBridgeVrfs(const RoutedVrfInfo &routing_vrf_info);

    /// @brief Walks the EVPN table of the routing VRF instance of a given
    /// LR.
    void WalkRoutingVrf(const boost::uuids::uuid &lr_uuid,
        const VnEntry *vn, bool update, bool withdraw);

    /// @brief Walks given Inet tables (IPv4 and IPv6).
    void WalkBridgeInetTables(InetUnicastAgentRouteTable *inet4,
        InetUnicastAgentRouteTable *inet6);

    /// @brief Find the routing VRF instance using a given virtual network.
    const VrfEntry *GetRoutingVrfUsingVn(const VnEntry *vn);

    /// @brief Find the routing VRF instance using a given route
    /// (AgentRoute).
    const VrfEntry *GetRoutingVrfUsingAgentRoute(const AgentRoute *rt);

    /// @brief Find the routing VRF instance using a given LR UUID.
    const VrfEntry *GetRoutingVrfUsingUuid(const boost::uuids::uuid &lr_uuid);

    /// @brief Find the UUID of the LR using a given route (AgentRoute).
    const boost::uuids::uuid GetLogicalRouterUuidUsingRoute(const AgentRoute *rt);

    /// @brief A pointer to the VxlanRoutingManager instance.
    VxlanRoutingManager *mgr_;

    /// @brief  The map between Logical router UUID and
    /// RoutedVrfInfo
    LrVrfInfoMap lr_vrf_info_map_;

    /// @brief The map between pointer to VirtualNetwork (a
    /// bridge or routing virtual network connected to some LR) and
    /// the LR's UUID.
    VnLrSet vn_lr_set_;

    /// @brief The set of walkers for Inet IPv4 tables of bridge VRF instances.
    InetTableWalker inet4_table_walker_;

    /// @brief The set of walkers for Inet IPv6 tables of bridge VRF instances.
    InetTableWalker inet6_table_walker_;

    DISALLOW_COPY_AND_ASSIGN(VxlanRoutingVrfMapper);
};

/// @brief This class manages routes leaking between bridge VRF instances
/// and the routing VRF instance. Routes are leaking is bi-directional:
/// a) first, during the forward stage interface routes with
/// LOCAL_VM_PORT_PEER are copied from each
/// bridge VRF inet table into the routing VRF inet and EVPN tables; b)
/// second, routes from the routing VRF are
/// redistributed amongst bridge VRF tables durging the backward stage.
/// The class extensively uses events notifications to trigger routes
/// leaking.
class VxlanRoutingManager {
public:

    /// @brief Constructs instance of the class and links to the Agent class
    /// instance. Since only one agent class instance works per system process,
    /// this implies that only one instance of VxlanRoutingManager exists.
    VxlanRoutingManager(Agent *agent);

    /// @brief Destroys the VxlanRoutingManager instance.
    virtual ~VxlanRoutingManager();

    /// @brief Registers handlers for events associated with changes in
    /// virtual networks (VnTable class) and VRF instances (VrfTable class).
    void Register();

    /// @brief Unregisters handlers for events associated with changes in
    /// virtual networks (VnTable class) and VRF instances (VrfTable class).
    void Shutdown();

    /// @brief A handler for changes (new/update/delete) in a virtual network
    /// (VnEntry class).
    void VnNotify(DBTablePartBase *partition, DBEntryBase *e);

    /// @brief A handler for changes (new/update/delete) in the virtual network
    /// from a bridge VRF.
    void BridgeVnNotify(const VnEntry *vn, VxlanRoutingVnState *vn_state);

    /// @brief A handler for changes (new/update/delete) in the virtual network
    /// from a routing VRF.
    void RoutingVnNotify(const VnEntry *vn, VxlanRoutingVnState *vn_state);

    /// @brief A handler for changes (new/update/delete) in a VRF instance
    /// (VrfEntry class).
    void VrfNotify(DBTablePartBase *partition, DBEntryBase *e);

    /// @brief Handler for changes (new/update/delete) in
    /// a VMI (VmInterface class).
    void VmiNotify(DBTablePartBase *partition, DBEntryBase *e);

    /// @brief Handler for changes (new/update/delete) in a route
    /// (EVPN or Inet). Main entry point for routes leaking.
    bool RouteNotify(DBTablePartBase *partition, DBEntryBase *e);

    /// Routes leaking functions

private:

    /// @brief Performs routes leaking between the Inet table of a bridge VRF
    /// instance and the EVPN table of the routing VRF instance.
    bool InetRouteNotify(DBTablePartBase *partition, DBEntryBase *e);

    /// @brief Performs routes leaking between the EVPN table of the routing
    /// VRF instance and the Inet table of the routing VRF instance.
    bool EvpnRouteNotify(DBTablePartBase *partition, DBEntryBase *e);

    /// @brief Removes redundant VrfNH path from a given route. These routes
    /// might arise with small chance in a bridge VRF inet tables when
    /// tunnels in the routing VRF instance arrive later then in the bridge VRF
    /// instance.
    void ClearRedundantVrfPath(DBEntryBase *e);

    /// @brief Handles deletion of a route in the EVPN table of the routing
    /// VRF instance.
    void WhenBridgeInetIntfWasDeleted(const InetUnicastRouteEntry *inet_rt,
        const VrfEntry *routing_vrf);

    /// @brief Handles deletion of a route in the Inet table of the routing
    /// VRF instance.
    void WhenRoutingEvpnRouteWasDeleted(const EvpnRouteEntry *routing_evpn_rt,
        const Peer* delete_from_peer);

public:

    /// @brief Deletes a given EVPN route from EVPN table of the routing
    /// VRF instance
    bool WithdrawEvpnRouteFromRoutingVrf
    (const VrfEntry *routing_vrf, DBTablePartBase *partition, DBEntryBase *e);

    /// @brief Performs advertisement and deletion of routing routes
    /// (with VrfNH) in bridge VRF instances. External tunnels and routes
    /// with a prefix that is not present in bridge VRF instance are
    /// selected for leaking
    bool LeakRoutesIntoBridgeTables(DBTablePartBase *partition,
        DBEntryBase *e,
        const boost::uuids::uuid &uuid,
        const VnEntry *vn,
        bool update = false);

    /// @brief Handles routing routes (with VrfNH) update in the routing VRF
    /// instance.
    void HandleSubnetRoute(const VrfEntry *vrf, bool bridge_vrf = false);

private:

    /// @brief deletes all routes in EVPN table of routing VRF
    void RoutingVrfDeleteAllRoutes(VrfEntry* rt_vrf);

    /// @brief Deletes subnet routes (actually, paths with VrfNH) in
    /// the given bridge VRF. This function is demanded at vn.c:618
    void DeleteSubnetRoute(const VrfEntry *vrf);
    //void DeleteSubnetRoute(const VrfEntry *vrf, VnIpam *ipam = NULL);

    /// @brief Deletes subnet routes from a specified virtual network
    /// (VirtualNetwork)
    void DeleteSubnetRoute(const VnEntry *vn,
        const std::string& vrf_name);

    /// @brief Delete routes to IPAM, specified by IP prefix and prefix
    /// length
    void DeleteIpamRoutes(const VnEntry *vn,
    const std::string& vrf_name,
    const IpAddress& ipam_prefix,
    const uint32_t plen);

    /// @brief Updates subnet routes (actually, paths with VrfNH) in
    /// the given bridge VRF
    void UpdateSubnetRoute(const VrfEntry *vrf,
                            const VrfEntry *routing_vrf);
public:

    /// @brief Updates Sandesh response
    void FillSandeshInfo(VxlanRoutingResp *resp);

    /// @brief Returns the ID of the listener to changes in the VnTable
    DBTable::ListenerId vn_listener_id() const {
        return vn_listener_id_;
    }

    /// @brief Returns the ID of the listener to changes in the VrfTable
    DBTable::ListenerId vrf_listener_id() const {
        return vrf_listener_id_;
    }

    /// @brief Returns the ID of the listener to changes in the InterfaceTable
    DBTable::ListenerId vmi_listener_id() const {
        return vmi_listener_id_;
    }

    /// @brief Returns the map between LR uuids and associated bridge and
    /// routing VRF instances
    const VxlanRoutingVrfMapper &vrf_mapper() const {
        return vrf_mapper_;
    }

    /// @brief Returns a pointer to the AgentRouteWalkerPtr object
    AgentRouteWalker* walker() {
        return walker_.get();
    }

private:

    /// Internal data of this class

    /// @brief A pointer to the Peer where all interface / composite of
    /// interfaces routes in routing VRF are linked to.
    static const Peer *routing_vrf_interface_peer_;

    /// @brief A pointer to the Peer where all BGP routes are stored
    static const Peer* routing_vrf_vxlan_bgp_peer_;

    /// @brief A pointer to the Agent instance.
    Agent *agent_;

    /// @brief A pointer to the walker to loop over INET tables
    /// in bridge VRF instances.
    AgentRouteWalkerPtr walker_;

    /// @brief An ID of the listener to changes in VnTable.
    DBTable::ListenerId vn_listener_id_;

    /// @brief An ID of the listener to changes in VrfTable.
    DBTable::ListenerId vrf_listener_id_;

    /// @brief An ID of the listener to changes in InterfaceTable.
    DBTable::ListenerId vmi_listener_id_;

    /// @brief A map between LR uuids and associated bridge and
    /// routing VRF instances.
    VxlanRoutingVrfMapper vrf_mapper_;

    /// @brief An always increasing counter for new paths (used to signal
    /// controoler about new routes).
    static uint32_t loc_sequence_;

    /// A mutex object to prevent simultaneous update of local sequence
    /// number property.
    static tbb::mutex mutex_;

    /// Friends declarations

    /// @brief Allows access to private members for the VxlanRoutingRouteWalker
    /// class.
    friend class VxlanRoutingRouteWalker;

    /// @brief Allows ControllerEcmpRoute to use private members of this class.
    friend class ControllerEcmpRoute;

    /// @brief Allows AgentXmppChannel to use private members of this class.
    friend class AgentXmppChannel;

    /// @brief Allows access to Xmpp advertisement functions via external class
    friend class AgentXmppChannelVxlanInterface;

    /// @brief Allows VxlanRoutingVrfMapper to use private members of
    /// this class.
    friend class VxlanRoutingVrfMapper;

    /// @brief Allows MetadataProxy to use private members of this class.
    friend class MetadataProxy;

    /// Auxilliary functions

    /// @brief Returns new value of a local sequence. Thread safe version
    static uint32_t GetNewLocalSequence();

    /// @brief Determines whether the address string contains an IPv4 address
    ///  as substring or not.
    static bool is_ipv4_string(const std::string& prefix_str);

    /// @brief Determines whether the address string contains an IPv6 address
    ///  as substring or not.
    static bool is_ipv6_string(const std::string& prefix_str);

    /// @brief Extracts length of IPv4 subnet address from the prefix string.
    static uint32_t ipv4_prefix_len(const std::string& prefix_str);

    /// @brief Extracts an IPv4 address string from the prefix string.
    static std::string ipv4_prefix(const std::string& prefix_str);

    /// @brief Extracts length of IPv6 subnet address from the prefix string.
    static uint32_t ipv6_prefix_len(const std::string& prefix_str);

    /// @brief Extracts an IPv6 address string from the prefix string.
    static std::string ipv6_prefix(const std::string& prefix_str);

    /// @brief Checks whether VxLAN routing manager is enabled or not.
    static bool IsVxlanAvailable(const Agent* agent);

    /// @brief Finds first occurence of a route with the given prefix (IP
    /// address and length) in Inet tables of bridge VRF instances connected
    /// to the given routing VRF instance (LR).
    std::string GetOriginVn(const VrfEntry* routing_vrf,
        const IpAddress& ip_addr,
        const uint8_t& plen);

    /// @brief Determines whether route prefix in the EVPN route is equal
    /// to the given pair of prefix IP address and length
    static bool RoutePrefixIsEqualTo(const EvpnRouteEntry* route,
        const IpAddress& prefix_ip,
        const uint32_t prefix_len);

    /// @brief Determines whether route prefix of the Inet route is equal
    /// to the given pair of prefix IP address and length
    static bool RoutePrefixIsEqualTo(const InetUnicastRouteEntry* route,
        const IpAddress& prefix_ip,
        const uint32_t prefix_len);

    /// @brief Determines whether the prefix address and the prefix length
    /// point to a host route (/32 for IPv4, /128 for IPv6) or
    /// to a subnet route.
    static bool IsHostRoute(const IpAddress& prefix_ip, uint32_t prefix_len);

    /// @brief Determines whether the given EVPN route points to a host or
    /// a subnet.
    static bool IsHostRoute(const EvpnRouteEntry *rt);

    /// @brief Determines whether the given EVPN route is a host one and
    /// belongs to a subnet of a local bridge VRF. During the search all
    /// subnets in all bridge VRF instances connected to the LR are traversed.
    bool IsHostRouteFromLocalSubnet(const EvpnRouteEntry *rt);

    /// @brief Determines if the given EVPN route has an interface NH or
    /// a composite of interfaces NH that belongs to the given
    /// bridge VRF instance.
    bool IsVrfLocalRoute(EvpnRouteEntry *routing_evpn_rt,
        VrfEntry *bridge_vrf);

    /// @brief Determines if the given EVPN route is already present
    /// in the given VRF
    bool IsLocalRoute(EvpnRouteEntry *routing_evpn_rt,
        VrfEntry *bridge_vrf);

    /// @brief Determines whether the given route has the path with
    /// a VRF nexthop (VrfNH)
    static bool HasVrfNexthop(const AgentRoute* rt);

    /// @brief Determines whether the given EVPN route has at least one path
    /// originating from BGP/XMPP (has Peer type BGP_PATH)
    bool HasBgpPeerPath(EvpnRouteEntry *evpn_rt);

    /// @brief Determines whether the pointer to the VRF instance is of routing
    ///  type.
    /// @return true if it is routing, otherwise return value is false.
    static bool IsRoutingVrf(const VrfEntry* vrf);

    /// @brief Determines whether the pointer to the VRF instance is of
    /// bridge type.
    /// @return true if it is routing, otherwise return value is false.
    static bool IsBridgeVrf(const VrfEntry* vrf);

    /// @brief Checks whether the VRF instance with the given name is routing
    /// or not.
    /// @return true if this VRF is routing, otherwise return value is false.
    static bool IsRoutingVrf(const std::string vrf_name, const Agent *agent);

    /// @brief Finds in the given route the path with a specified Peer type
    static const AgentPath* FindPathWithGivenPeer(
        const AgentRoute *inet_rt,
        const Peer::Type peer_type);

    /// @brief Finds in the given route the path with a specified Peer type
    /// and a specified nexthop type
    static const AgentPath* FindPathWithGivenPeerAndNexthop(
        const AgentRoute *inet_rt,
        const Peer::Type peer_type,
        const NextHop::Type nh_type,
        bool strict_match = true);

    /// @brief Finds in the given route the path with the given Peer type
    /// and interface nexthop (InterfaceNH).
    static const AgentPath* FindInterfacePathWithGivenPeer(
        const AgentRoute *inet_rt,
        const Peer::Type peer_type,
        bool strict_match = true);

    /// @brief Finds in the given route the path which has
    /// the BGP_PEER Peer type and the Interface nexthop type.
    /// Such path presumably points to BGPaaS advertised route.
    static const AgentPath *FindInterfacePathWithBgpPeer(
        const AgentRoute *inet_rt,
        bool strict_match = true);

    /// @brief Finds in the given route the path which has the LOCAL_VM_PEER
    /// peer type and the Interface nexthop type.
    static const AgentPath *FindInterfacePathWithLocalVmPeer(
        const AgentRoute *inet_rt,
        bool strict_match = true);

    /// @brief Finds in the given route the path that was announced using
    /// BGPaaS. It is expected that this path has BGP_PEER peer type
    /// and the interface or composite nexthop.
    const AgentPath *FindBGPaaSPath(const InetUnicastRouteEntry *rt);

    /// @brief Advertises BGPaaS interface path in the routing VRF instance
    /// by selecting corresponding path components in a path from
    /// the bridge VRF instance
    void AdvertiseBGPaaSRoute(const IpAddress& prefix_ip, uint32_t prefix_len,
        const AgentPath* path, EvpnAgentRouteTable *evpn_table);

    /// @brief Checks whether IP prefixes correspond to external
    /// EVPN Type5 tunnel routes.
    /// @return true if all nh_addresses points to local comute nodes
    /// (fabric policy VRF). Otherwise returns false.
    static bool IsExternalType5(const std::vector<IpAddress>& nh_addreses,
        const Agent *agent);

    /// @brief Checks whether a route with the given prefix and prefix len
    /// is available in the given EVPN table and is external.
    static bool IsExternalType5(EvpnAgentRouteTable *rt_table,
        const IpAddress& ip_addr,
        uint32_t plen,
        uint32_t ethernet_tag,
        const Peer* peer);

    /// @brief Returns the MAC address for the IP of a given
    /// neighbouring compute
    static MacAddress NbComputeMac(const Ip4Address& compute_ip,
        const Agent *agent);

    /// XMPP Advertising functions

    /// @brief Allocates and returns a new key for the VxLAN tunnel to
    /// the given router
    TunnelNHKey* AllocateTunnelNextHopKey(const IpAddress& dip,
        const MacAddress& dmac) const;

    /// @brief Advertises an EVPN route received using XMPP channel
    void XmppAdvertiseEvpnRoute(const IpAddress& prefix_ip,
        const int prefix_len, uint32_t vxlan_id, const std::string vrf_name,
        const RouteParameters& params, const Peer *bgp_peer);

    /// @brief Advertises an Inet route received using XMPP channel
    void XmppAdvertiseInetRoute(const IpAddress& prefix_ip,
        const int prefix_len, uint32_t vxlan_id, const std::string vrf_name,
        const RouteParameters& params, const Peer *bgp_peer);

    /// @brief Advertises an Inet route received from EVPN table
    void XmppAdvertiseInetRoute(const IpAddress& prefix_ip,
        const int prefix_len, const std::string vrf_name,
        const AgentPath*);

    /// @brief Advertises in the EVPN table a tunnel route that arrived
    /// via XMPP channel. Must be called only from XmppAdvertiseInetRoute.
    void XmppAdvertiseEvpnTunnel(
        EvpnAgentRouteTable *inet_table, const IpAddress& prefix_ip,
        const int prefix_len, uint32_t vxlan_id, const std::string vrf_name,
        const RouteParameters& params, const Peer *bgp_peer);

    /// @brief Advertises in the EVPN table an interface route that arrived
    /// via XMPP channel. Must be called only from XmppAdvertiseInetRoute.
    void XmppAdvertiseEvpnInterface(
        EvpnAgentRouteTable *inet_table, const IpAddress& prefix_ip,
        const int prefix_len, uint32_t vxlan_id, const std::string vrf_name,
        const RouteParameters& params, const Peer *bgp_peer);

    /// @brief Advertises in the Inet table a tunnel route that arrived
    /// via XMPP channel. Must be called only from XmppAdvertiseInetRoute.
    void XmppAdvertiseInetTunnel(
        InetUnicastAgentRouteTable *inet_table, const IpAddress& prefix_ip,
        const int prefix_len, uint32_t vxlan_id, const std::string vrf_name,
        const RouteParameters& params, const Peer *bgp_peer);

    /// @brief Advertises in the Inet table a tunnel route that arrived
    /// via XMPP channel. Must be called only from XmppAdvertiseInetRoute.
    void XmppAdvertiseInetTunnel(
        InetUnicastAgentRouteTable *inet_table, const IpAddress& prefix_ip,
        const int prefix_len, const std::string vrf_name,
        const AgentPath* path);

    /// @brief Advertises in the Inet table an interface route that arrived
    /// via XMPP channel. Must be called only from XmppAdvertiseInetRoute.
    void XmppAdvertiseInetInterfaceOrComposite(
        InetUnicastAgentRouteTable *inet_table, const IpAddress& prefix_ip,
        const int prefix_len, const std::string vrf_name,
        const AgentPath* path);

    /// Templates

    /// @brief Checks whether nexthops in the given autogen item point to
    /// external network
    template <class ItType>
    static bool IsExternalType5(ItType *item, const Agent *agent);

    /// @brief Converts item's (EnetItemType for EVPN / ItemType for Inet)
    /// nexthops into the list of IP addresses (IpAddress)
    template <class ItType>
    static std::vector<IpAddress> ItemNexthopsToVector(ItType *item);

    /// @brief Adds an interface or a composite of interfaces nexthops to
    /// the list of components NH keys needed for construction of the
    /// a mixed composite.
    template<typename NhType>
    static void AddInterfaceComponentToList(
        const std::string& prefix_str,
        const std::string& vrf_name,
        const NhType &nh_item,
        ComponentNHKeyList& comp_nh_list);

    /// @brief Finds a route with the given prefix address and len
    /// in the EVPN table
    static AgentRoute *FindEvpnOrInetRoute(const Agent *agent,
        const std::string &vrf_name,
        const IpAddress &ip_addr,
        uint32_t prefix_len,
        const autogen::EnetNextHopType &nh_item);

    /// @brief Finds a route with the given prefix address and len
    /// in the Inet table
    static AgentRoute *FindEvpnOrInetRoute(const Agent *agent,
        const std::string &vrf_name,
        const IpAddress &ip_addr,
        uint32_t prefix_len,
        const autogen::NextHopType &nh_item);

    /// Routes copying functions

    /// @brief Deletes interface path specified with IP prefix, prefix
    /// length and Peer from the EVPN table.
    static void DeleteOldInterfacePath(const IpAddress &prefix_ip,
        const uint32_t plen,
        const Peer *peer,
        EvpnAgentRouteTable *evpn_table);

    /// @brief Copies the path to the prefix address into the EVPN table
    /// with the given Peer. The function is used during routes leaking
    /// between bridge VRF Inet and routing EVPN tables.
    static void CopyInterfacePathToEvpnTable(const AgentPath* path,
        const IpAddress &prefix_ip,
        const uint32_t plen,
        const Peer *peer,
        const RouteParameters &params,
        EvpnAgentRouteTable *evpn_table);

    /// @brief
    static void DeleteOldInterfacePath(const IpAddress &prefix_ip,
        const uint32_t plen,
        const Peer *peer,
        InetUnicastAgentRouteTable *inet_table);

    /// @brief Copies the path to the prefix address into the EVPN table
    /// with the given Peer. The function is used during routes leaking
    /// between routing VRF EVPN and Inet tables.
    void CopyPathToInetTable(const AgentPath* path,
        const IpAddress &prefix_ip,
        const uint32_t plen,
        const Peer *peer,
        const RouteParameters &params,
        InetUnicastAgentRouteTable *inet_table);

public:

    /// @brief Prints EVPN table of the given VRF instance.
    static void PrintEvpnTable(const VrfEntry* const_vrf);

    /// @brief Prints IPv4 Inet table of the given VRF instance.
    static void PrintInetTable(const VrfEntry* const_vrf);

    /// @brief Prints all virtual networks attached to logical routers.
    static void ListAttachedVns();

    DISALLOW_COPY_AND_ASSIGN(VxlanRoutingManager);
};

#include <oper/vxlan_templates.cc>

#endif
