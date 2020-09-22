/*
 * Copyright (c) 2018 Juniper Networks, Inc. All rights reserved.
 */

#include "base/os.h"
#include "testing/gunit.h"

#include <base/logging.h>
#include <io/event_manager.h>
#include <io/test/event_manager_test.h>
#include <tbb/task.h>
#include <base/task.h>
#include "net/bgp_af.h"
#include <cmn/agent_cmn.h>

#include "cfg/cfg_init.h"
#include "pkt/pkt_init.h"
#include "services/services_init.h"
#include "vrouter/ksync/ksync_init.h"
#include "oper/interface_common.h"
#include "oper/nexthop.h"
#include "oper/tunnel_nh.h"
#include "route/route.h"
#include "oper/vrf.h"
#include "oper/mpls.h"
#include "oper/vm.h"
#include "oper/vn.h"
#include "oper/physical_device_vn.h"
#include "filter/acl.h"
#include "test_cmn_util.h"
#include "vr_types.h"

#include "xmpp/xmpp_init.h"
#include "xmpp/test/xmpp_test_util.h"
#include "vr_types.h"
#include "control_node_mock.h"
#include "xml/xml_pugi.h"
#include "oper/vxlan_routing_manager.h"
#include "controller/controller_init.h"
#include <controller/controller_export.h>

using namespace pugi;
#define L3_VRF_OFFSET 100

struct PortInfo input1[] = {
    {"vnet10", 10, "1.1.1.10", "00:00:01:01:01:10", 1, 10},
    {"vnet11", 11, "1.1.1.11", "00:00:01:01:01:11", 1, 11},
};

struct PortInfo input2[] = {
    {"vnet20", 20, "2.2.2.20", "00:00:02:02:02:20", 2, 20},
};

IpamInfo ipam_1[] = {
    {"1.1.1.0", 24, "1.1.1.200", true},
};

IpamInfo ipam_2[] = {
    {"2.2.2.0", 24, "2.2.2.200", true},
};

void RouterIdDepInit(Agent *agent) {
}

class VxlanRoutingTest : public ::testing::Test {
protected:
    VxlanRoutingTest() {
    }

    virtual void SetUp() {
        client->Reset();
        agent_ = Agent::GetInstance();
        bgp_peer_ = NULL;
    }

    virtual void TearDown() {
    }

    void SetupEnvironment() {
        bgp_peer_ = CreateBgpPeer("127.0.0.1", "remote");
        client->WaitForIdle();
        AddIPAM("vn1", ipam_1, 1);
        AddIPAM("vn2", ipam_2, 1);
        CreateVmportEnv(input1, 2);
        CreateVmportEnv(input2, 1);
        AddLrVmiPort("lr-vmi-vn1", 91, "1.1.1.99", "vrf1", "vn1",
                    "instance_ip_1", 1);
        AddLrVmiPort("lr-vmi-vn2", 92, "2.2.2.99", "vrf2", "vn2",
                    "instance_ip_2", 2);
        client->WaitForIdle();
    }

    void DeleteEnvironment(bool vxlan_enabled) {
        DelIPAM("vn1");
        DelIPAM("vn2");
        DelNode("project", "admin");
        DeleteVmportEnv(input1, 2, true);
        DeleteVmportEnv(input2, 1, true);
        DelLrVmiPort("lr-vmi-vn1", 91, "1.1.1.99", "vrf1", "vn1",
                    "instance_ip_1", 1);
        DelLrVmiPort("lr-vmi-vn2", 92, "2.2.2.99", "vrf2", "vn2",
                    "instance_ip_2", 2);
        DeleteBgpPeer(bgp_peer_);
        client->WaitForIdle(5);
        EXPECT_TRUE(VrfGet("vrf1") == NULL);
        EXPECT_TRUE(VrfGet("vrf2") == NULL);
        EXPECT_TRUE(agent_->oper_db()->vxlan_routing_manager()->vrf_mapper().
                    IsEmpty());
        EXPECT_TRUE(agent_->oper_db()->vxlan_routing_manager()->vrf_mapper().
                    IsEmpty());
    }

    void ValidateBridge(const std::string &bridge_vrf,
                        const std::string &routing_vrf,
                        const Ip4Address &addr,
                        uint8_t plen,
                        bool participate) {
        InetUnicastRouteEntry *rt =
            RouteGet(bridge_vrf, addr, plen);
        if (participate) {
            InetUnicastRouteEntry *default_rt =
            RouteGet(bridge_vrf, Ip4Address::from_string("0.0.0.0"), 0);
            EXPECT_TRUE( default_rt == NULL);

            EXPECT_TRUE(rt->GetActivePath()->peer()->GetType() ==
                        Peer::EVPN_ROUTING_PEER);
            const VrfNH *nh = dynamic_cast<const VrfNH *>
                (rt->GetActiveNextHop());
            EXPECT_TRUE(nh->GetVrf()->GetName() == routing_vrf);
        } else {
            if (rt == NULL)
                return;

            EXPECT_TRUE(rt->GetActivePath()->peer()->GetType() !=
                        Peer::EVPN_ROUTING_PEER);
            const VrfNH *nh = dynamic_cast<const VrfNH *>
                (rt->GetActiveNextHop());
            EXPECT_TRUE(nh == NULL);
        }
    }

    void ValidateBridgeRemote(const std::string &bridge_vrf,
                              const std::string &routing_vrf,
                              const Ip4Address &addr,
                              uint8_t plen,
                              bool participate) {
        InetUnicastRouteEntry *rt =
            RouteGet(bridge_vrf, addr, plen);
        if (participate) {
            EXPECT_TRUE(rt->GetActivePath()->peer()->GetType() ==
                        Peer::BGP_PEER);
            const VrfNH *nh = dynamic_cast<const VrfNH *>
                (rt->GetActiveNextHop());
            EXPECT_TRUE(nh->GetVrf()->GetName() == routing_vrf);
        } else {
            if (rt == NULL)
                return;

            EXPECT_TRUE(rt->GetActivePath()->peer()->GetType() !=
                        Peer::BGP_PEER);
            const VrfNH *nh = dynamic_cast<const VrfNH *>
                (rt->GetActiveNextHop());
            EXPECT_TRUE(nh == NULL);
        }
    }

    void ValidateRouting(const std::string &routing_vrf,
                         const Ip4Address &addr,
                         uint8_t plen,
                         const std::string &dest_name,
                         bool present,
                         const std::string &origin_vn = "") {
        InetUnicastRouteEntry *rt =
            RouteGet(routing_vrf, addr, plen);
        if (present) {
            EXPECT_TRUE(rt != NULL);
            const InterfaceNH *intf_nh =
                dynamic_cast<const InterfaceNH *>(rt->GetActiveNextHop());
            if (intf_nh) {
                EXPECT_TRUE(intf_nh->GetInterface()->name() == dest_name);
                EXPECT_TRUE(intf_nh->IsVxlanRouting());
            }
            const TunnelNH *tunnel_nh =
                dynamic_cast<const TunnelNH *>(rt->GetActiveNextHop());
            if (tunnel_nh) {
                EXPECT_TRUE(tunnel_nh->GetDip()->to_string() == dest_name);
                EXPECT_TRUE(tunnel_nh->rewrite_dmac().IsZero() == false);
            }
            const AgentPath *path = rt->GetActivePath();
            if (path) {
                EXPECT_TRUE(path->origin_vn() == origin_vn);
            }
        } else {
            EXPECT_TRUE(rt == NULL);
        }
    }

    BgpPeer *bgp_peer_;
    Agent *agent_;
};

TEST_F(VxlanRoutingTest, Basic) {
    using boost::uuids::nil_uuid;

    SetupEnvironment();
    AddLrRoutingVrf(1);
    EXPECT_TRUE(VmInterfaceGet(10)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(11)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(20)->logical_router_uuid() == nil_uuid());
    ValidateRouting("l3evpn_1", Ip4Address::from_string("1.1.1.10"), 32,
                    "vnet10", false);
    ValidateRouting("l3evpn_1", Ip4Address::from_string("1.1.1.11"), 32,
                    "vnet11", false);
    ValidateRouting("l3evpn_1", Ip4Address::from_string("2.2.2.20"), 32,
                    "vnet20", false);
    // No subnet route is added as no bdidge vrf
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("2.2.2.0"), 24, false);
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.10"), 32, false);
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.11"), 32, false);
    ValidateBridge("vrf2", "l3evpn_1",
                   Ip4Address::from_string("2.2.2.20"), 32, false);
    DelLrRoutingVrf(1);
    DeleteEnvironment(true);
}
TEST_F(VxlanRoutingTest, Route_1) {
    using boost::uuids::nil_uuid;

    SetupEnvironment();
    AddLrRoutingVrf(1);
    AddLrBridgeVrf("vn1", 1);
    EXPECT_TRUE(VmInterfaceGet(10)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(11)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(20)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(91)->logical_router_uuid() != nil_uuid());
    ValidateRouting("l3evpn_1", Ip4Address::from_string("1.1.1.10"), 32,
                    "vnet10", true, "vn1");
    ValidateRouting("l3evpn_1", Ip4Address::from_string("1.1.1.11"), 32,
                    "vnet11", true, "vn1");
    ValidateRouting("l3evpn_1", Ip4Address::from_string("2.2.2.20"), 32,
                    "vnet20", false);
    // only one bridge vrf so no subnet route gets added for vn2
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("2.2.2.0"), 24, false);
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.10"), 32, true);
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.11"), 32, true);
    ValidateBridge("vrf2", "l3evpn_1",
                   Ip4Address::from_string("2.2.2.20"), 32, false);

    // Trigger vxlan routing manager's walker
    VxlanRoutingRouteWalker *walker = dynamic_cast<VxlanRoutingRouteWalker*>(
                             agent_->oper_db()->vxlan_routing_manager()->walker());
    if (walker) {
        VrfEntry *vrf = Agent::GetInstance()->vrf_table()->FindVrfFromName("vrf1");
        if (vrf != NULL) {
            walker->StartRouteWalk(vrf);
        }
    }
    client->WaitForIdle();
    // Validate the routes again
    ValidateRouting("l3evpn_1", Ip4Address::from_string("1.1.1.10"), 32,
                    "vnet10", true, "vn1");
    ValidateRouting("l3evpn_1", Ip4Address::from_string("1.1.1.11"), 32,
                    "vnet11", true, "vn1");
    ValidateRouting("l3evpn_1", Ip4Address::from_string("2.2.2.20"), 32,
                    "vnet20", false);
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("2.2.2.0"), 24, false);
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.10"), 32, true);
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.11"), 32, true);
    ValidateBridge("vrf2", "l3evpn_1",
                   Ip4Address::from_string("2.2.2.20"), 32, false);

    DeleteEnvironment(true);
    client->WaitForIdle();
    DelLrBridgeVrf("vn1", 1);
    DelLrRoutingVrf(1);
}

TEST_F(VxlanRoutingTest, Route_2) {
    using boost::uuids::nil_uuid;

    SetupEnvironment();
    AddLrRoutingVrf(1);
    AddLrBridgeVrf("vn1", 1);
    EXPECT_TRUE(VmInterfaceGet(10)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(11)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(20)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(91)->logical_router_uuid() != nil_uuid());
    ValidateRouting("l3evpn_1", Ip4Address::from_string("1.1.1.10"), 32,
                    "vnet10", true, "vn1");
    ValidateRouting("l3evpn_1", Ip4Address::from_string("1.1.1.11"), 32,
                    "vnet11", true, "vn1");
    ValidateRouting("l3evpn_1", Ip4Address::from_string("2.2.2.20"), 32,
                    "vnet20", false);
    // only one bridge vrf so no subnet route gets added for vn2
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("2.2.2.0"), 24, false);
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.10"), 32, true);
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.11"), 32, true);
    ValidateBridge("vrf2", "l3evpn_1",
                   Ip4Address::from_string("2.2.2.20"), 32, false);
    DelLrBridgeVrf("vn1", 1);
    DelLrRoutingVrf(1);
    DeleteEnvironment(true);
}

TEST_F(VxlanRoutingTest, Route_3) {
    using boost::uuids::nil_uuid;

    SetupEnvironment();
    AddLrRoutingVrf(1);
    AddLrBridgeVrf("vn1", 1);
    AddLrBridgeVrf("vn2", 1);
    EXPECT_TRUE(VmInterfaceGet(10)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(11)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(20)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(91)->logical_router_uuid() != nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(92)->logical_router_uuid() != nil_uuid());
    ValidateRouting("l3evpn_1", Ip4Address::from_string("1.1.1.10"), 32,
                    "vnet10", true, "vn1");
    ValidateRouting("l3evpn_1", Ip4Address::from_string("1.1.1.11"), 32,
                    "vnet11", true, "vn1");
    ValidateRouting("l3evpn_1", Ip4Address::from_string("2.2.2.20"), 32,
                    "vnet20", true, "vn2");
    // validate subnet route for vn2 gets added to vrf1 inet table
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("2.2.2.0"), 24, true);
    // validate subnet route for vn1 gets added to vrf2 inet table
    ValidateBridge("vrf2", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.0"), 24, true);
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.10"), 32, true);
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.11"), 32, true);
    ValidateBridge("vrf2", "l3evpn_1",
                   Ip4Address::from_string("2.2.2.20"), 32, true);
    DelLrBridgeVrf("vn1", 1);
    DelLrBridgeVrf("vn2", 1);
    DelLrRoutingVrf(1);
    DeleteEnvironment(true);
}

TEST_F(VxlanRoutingTest, Route_4) {
    using boost::uuids::nil_uuid;

    SetupEnvironment();
    AddLrRoutingVrf(1);
    AddLrRoutingVrf(2);
    AddLrBridgeVrf("vn1", 2);
    AddLrBridgeVrf("vn2", 1);
    EXPECT_TRUE(VmInterfaceGet(10)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(11)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(20)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(91)->logical_router_uuid() != nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(92)->logical_router_uuid() != nil_uuid());
    ValidateRouting("l3evpn_1", Ip4Address::from_string("1.1.1.10"), 32,
                    "vnet10", false);
    ValidateRouting("l3evpn_2", Ip4Address::from_string("1.1.1.10"), 32,
                    "vnet10", true, "vn1");
    ValidateRouting("l3evpn_2", Ip4Address::from_string("1.1.1.11"), 32,
                    "vnet11", true, "vn1");
    ValidateRouting("l3evpn_1", Ip4Address::from_string("2.2.2.20"), 32,
                    "vnet20", true, "vn2");
    // only one bridge vn added in Lr 2, verify no subnet route
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("2.2.2.0"), 24, false);
    // only one bridge vn added in Lr 1, verify no subnet route
    ValidateBridge("vrf2", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.0"), 24, false);
    ValidateBridge("vrf1", "l3evpn_2",
                   Ip4Address::from_string("1.1.1.10"), 32, true);
    ValidateBridge("vrf1", "l3evpn_2",
                   Ip4Address::from_string("1.1.1.11"), 32, true);
    ValidateBridge("vrf2", "l3evpn_1",
                   Ip4Address::from_string("2.2.2.20"), 32, true);
    DelLrBridgeVrf("vn1", 2);
    DelLrBridgeVrf("vn2", 1);
    DelLrRoutingVrf(1);
    DelLrRoutingVrf(2);
    DeleteEnvironment(true);
}

TEST_F(VxlanRoutingTest, Route_5) {
    using boost::uuids::nil_uuid;

    SetupEnvironment();
    AddLrRoutingVrf(1);
    AddLrBridgeVrf("vn1", 1);
    EXPECT_TRUE(VmInterfaceGet(10)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(11)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(20)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(91)->logical_router_uuid() != nil_uuid());
    MacAddress dummy_mac;
    BridgeTunnelRouteAdd(bgp_peer_, "l3evpn_1", TunnelType::VxlanType(),
                         Ip4Address::from_string("100.1.1.11"),
                         101, dummy_mac,
                         Ip4Address::from_string("1.1.1.20"),
                         32, "00:00:99:99:99:99");
    client->WaitForIdle();
    ValidateRouting("l3evpn_1", Ip4Address::from_string("1.1.1.10"), 32,
                    "vnet10", true, "vn1");
    ValidateRouting("l3evpn_1", Ip4Address::from_string("1.1.1.11"), 32,
                    "vnet11", true, "vn1");
    ValidateRouting("l3evpn_1", Ip4Address::from_string("1.1.1.20"), 32,
                    "100.1.1.11", true);
    ValidateRouting("l3evpn_1", Ip4Address::from_string("2.2.2.20"), 32,
                    "vnet20", false);
    // only one bridge vn added , verify no subnet route
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("2.2.2.0"), 24, false);
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.10"), 32, true);
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.11"), 32, true);
    ValidateBridge("vrf2", "l3evpn_1",
                   Ip4Address::from_string("2.2.2.20"), 32, false);
    EvpnAgentRouteTable::DeleteReq(bgp_peer_, "l3evpn_1",
                                   MacAddress(),
                                   Ip4Address::from_string("1.1.1.20"), 32, 0, NULL);
    DelLrBridgeVrf("vn1", 1);
    DelLrRoutingVrf(1);
    DeleteEnvironment(true);
}

TEST_F(VxlanRoutingTest, Route_6) {
    using boost::uuids::nil_uuid;

    SetupEnvironment();
    AddLrRoutingVrf(1);
    AddLrRoutingVrf(2);
    AddLrBridgeVrf("vn1", 1);
    EXPECT_TRUE(VmInterfaceGet(10)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(11)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(20)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(91)->logical_router_uuid() != nil_uuid());
#if 0
    InetUnicastRouteEntry *rt1 =
        RouteGet("l3evpn_1", Ip4Address::from_string("1.1.1.10"), 32);
    InetUnicastRouteEntry *rt2 =
        RouteGet("l3evpn_1", Ip4Address::from_string("1.1.1.11"), 32);
    ValidateRouting("l3evpn_1", Ip4Address::from_string("1.1.1.10"), 32,
                    "vnet10", (rt2 == NULL));
    ValidateRouting("l3evpn_1", Ip4Address::from_string("1.1.1.11"), 32,
                    "vnet11", (rt1 == NULL));
    ValidateRouting("l3evpn_1", Ip4Address::from_string("2.2.2.20"), 32,
                    "vnet20", false);
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("0.0.0.0"), 0, true);
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.10"), 32, (rt2 == NULL));
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.11"), 32, (rt1 == NULL));
    ValidateBridge("vrf2", "l3evpn_1",
                   Ip4Address::from_string("2.2.2.20"), 32, false);
#endif
    DelLrBridgeVrf("vn1", 1);
    DelLrRoutingVrf(1);
    DelLrRoutingVrf(2);
    DeleteEnvironment(true);
}

TEST_F(VxlanRoutingTest, Route_7) {
    using boost::uuids::nil_uuid;

    SetupEnvironment();
    std::stringstream name_ss;
    int lr_id = 1;
    name_ss << "l3evpn_" << lr_id;
    AddNode("logical-router", name_ss.str().c_str(), lr_id);
    AddLrBridgeVrf("vn1", 1, "snat-routing");
    EXPECT_TRUE(VmInterfaceGet(91) == NULL);
    DelLrBridgeVrf("vn1", 1);
    DelNode("logical-router", "l3evpn_1");
    DeleteEnvironment(true);
}

// Adding EVPN Type5 route to LR evpn table and verify it gets replicated
// to bridge vrf tables
TEST_F(VxlanRoutingTest, Lrvrf_Evpn_Type5_RouteAdd) {
    bgp_peer_ = CreateBgpPeer("127.0.0.1", "remote");
    using boost::uuids::nil_uuid;
    struct PortInfo input1[] = {
        {"vnet1", 1, "1.1.1.10", "00:00:01:01:01:10", 1, 1},
    };
    IpamInfo ipam_info_1[] = {
        {"1.1.1.0", 24, "1.1.1.254", true},
    };

    struct PortInfo input2[] = {
        {"vnet2", 20, "2.2.2.20", "00:00:02:02:02:20", 2, 20},
    };
    IpamInfo ipam_info_2[] = {
        {"2.2.2.0", 24, "2.2.2.200", true},
    };

    struct PortInfo input3[] = {
        {"vnet3", 30, "3.3.3.30", "00:00:03:03:03:30", 3, 30},
    };
    IpamInfo ipam_info_3[] = {
        {"3.3.3.0", 24, "3.3.3.200", true},
    };

    // Bridge vrf
    AddIPAM("vn1", ipam_info_1, 1);
    AddIPAM("vn2", ipam_info_2, 1);
    CreateVmportEnv(input1, 1);
    CreateVmportEnv(input2, 1);
    AddLrVmiPort("lr-vmi-vn1", 91, "1.1.1.99", "vrf1", "vn1",
            "instance_ip_1", 1);
    AddLrVmiPort("lr-vmi-vn2", 92, "2.2.2.99", "vrf2", "vn2",
            "instance_ip_2", 2);

    const char *routing_vrf_name = "l3evpn_1";
    AddLrRoutingVrf(1);
    AddLrBridgeVrf("vn1", 1);

    EXPECT_TRUE(VmInterfaceGet(1)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(20)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(91)->logical_router_uuid() != nil_uuid());
    ValidateRouting(routing_vrf_name, Ip4Address::from_string("1.1.1.10"), 32,
            "vnet1", true, "vn1");
    ValidateRouting(routing_vrf_name, Ip4Address::from_string("2.2.2.20"), 32,
            "vnet2", false);

    // check to see if the local port route added to the bridge vrf inet
    ValidateBridge("vrf1", routing_vrf_name,
            Ip4Address::from_string("1.1.1.10"), 32, true);

    // since vn2 is not included in the LR,
    // check to see no route add by peer:EVPN_ROUTING_PEER
    ValidateBridge("vrf2", routing_vrf_name,
            Ip4Address::from_string("2.2.2.20"), 32, false);

    // checking routing vrf have valid VXLAN ID
    VrfEntry *routing_vrf= VrfGet(routing_vrf_name);
    EXPECT_TRUE(routing_vrf->vxlan_id() != VxLanTable::kInvalidvxlan_id);

    // Test Type 5 route add/del in LR vrf
    stringstream ss_node;
    autogen::EnetItemType item;
    SecurityGroupList sg;
    item.entry.nlri.af = BgpAf::L2Vpn;
    item.entry.nlri.safi = BgpAf::Enet;
    item.entry.nlri.address="10.10.10.10";
    item.entry.nlri.ethernet_tag = 0;
    autogen::EnetNextHopType nh;
    nh.af = Address::INET;
    nh.address = "10.10.10.10";;
    nh.label = routing_vrf->vxlan_id();
    item.entry.next_hops.next_hop.push_back(nh);
    item.entry.med = 0;

    // Add type5 route 4.4.4.0/24 to lr evpn table
    bgp_peer_->GetAgentXmppChannel()->AddEvpnRoute(routing_vrf_name,
            "00:00:00:00:00:00",
            Ip4Address::from_string("4.4.4.0"),
            24, &item);
    client->WaitForIdle();

    // Validate route is copied to bridge vrf
    InetUnicastRouteEntry *rt1 =
        RouteGet(VrfGet("vrf1")->GetName(), Ip4Address::from_string("4.4.4.0"), 24);
    EXPECT_TRUE( rt1 != NULL);

    // Verify route for local vm port is still present
    ValidateBridge("vrf1", routing_vrf_name,
            Ip4Address::from_string("1.1.1.10"), 32, true);

    AddIPAM("vn3", ipam_info_3, 1);
    CreateVmportEnv(input3, 1);
    AddLrVmiPort("lr-vmi-vn3", 93, "3.3.3.99", "vrf3", "vn3",
            "instance_ip_3", 3);
    client->WaitForIdle();
    AddLrBridgeVrf("vn3", 1);
    client->WaitForIdle();

    // check to see if the subnet route for vn3 added to the bridge vrf vrf1 inet table
    ValidateBridge("vrf1", routing_vrf_name,
            Ip4Address::from_string("3.3.3.0"), 24, true);

    // check to see if the subnet route for vn1 added to the bridge vrf vrf3 inet table
    ValidateBridge("vrf3", routing_vrf_name,
            Ip4Address::from_string("1.1.1.0"), 24, true);

    // Verify type5 route added to Lr evpn table is copied to bdidge vrf, vrf3 inet table
    InetUnicastRouteEntry *static_rt_vrf3 =
        RouteGet("vrf3", Ip4Address::from_string("4.4.4.0"), 24);
    EXPECT_TRUE( static_rt_vrf3 != NULL);

    // Send rt delete in lr vrf and see route gets deleted in bridge vrf
    EvpnAgentRouteTable *rt_table1 = static_cast<EvpnAgentRouteTable *>
            (agent_->vrf_table()->GetEvpnRouteTable(routing_vrf_name));
    rt_table1->DeleteReq(bgp_peer_->GetAgentXmppChannel()->bgp_peer_id(),
        routing_vrf_name,
        MacAddress::FromString("00:00:00:00:00:00"),
        Ip4Address::from_string("4.4.4.0"),
        24, 0,
        new ControllerVmRoute(bgp_peer_->GetAgentXmppChannel()->bgp_peer_id()));
    client->WaitForIdle();

    InetUnicastRouteEntry *rt_del =
        RouteGet("vrf1", Ip4Address::from_string("4.4.4.0"), 24);
    EXPECT_TRUE( rt_del == NULL);

    InetUnicastRouteEntry *rt_del_vrf3 =
        RouteGet(VrfGet("vrf3")->GetName(), Ip4Address::from_string("4.4.4.0"), 24);
    EXPECT_TRUE( rt_del_vrf3 == NULL);

    // Clean up
    DelIPAM("vn1");
    DelIPAM("vn2");
    DelIPAM("vn3");
    DelNode("project", "admin");
    DeleteVmportEnv(input1, 2, true);
    DeleteVmportEnv(input2, 1, true);
    DeleteVmportEnv(input3, 1, true);
    DelLrVmiPort("lr-vmi-vn1", 91, "1.1.1.99", "vrf1", "vn1",
            "instance_ip_1", 1);
    DelLrVmiPort("lr-vmi-vn2", 92, "2.2.2.99", "vrf2", "vn2",
            "instance_ip_2", 2);
    DelLrVmiPort("lr-vmi-vn3", 93, "3.3.3.99", "vrf3", "vn3",
            "instance_ip_3", 3);
    client->WaitForIdle();
    DelLrBridgeVrf("vn3", 1);
    DelLrRoutingVrf(1);
    DeleteBgpPeer(bgp_peer_);
    client->WaitForIdle(5);
    EXPECT_TRUE(VrfGet("vrf1") == NULL);
    EXPECT_TRUE(VrfGet("vrf2") == NULL);
    EXPECT_TRUE(VrfGet("vrf3") == NULL);
    EXPECT_TRUE(agent_->oper_db()->vxlan_routing_manager()->vrf_mapper().
            IsEmpty());
    EXPECT_TRUE(agent_->oper_db()->vxlan_routing_manager()->vrf_mapper().
            IsEmpty());
    client->WaitForIdle();

}

TEST_F(VxlanRoutingTest, SubnetRoute) {
    using boost::uuids::nil_uuid;
    SetupEnvironment();
    AddLrRoutingVrf(1);
    AddLrBridgeVrf("vn1", 1);
    AddLrBridgeVrf("vn2", 1);
    EXPECT_TRUE(VmInterfaceGet(10)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(11)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(20)->logical_router_uuid() == nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(91)->logical_router_uuid() != nil_uuid());
    EXPECT_TRUE(VmInterfaceGet(92)->logical_router_uuid() != nil_uuid());
    ValidateRouting("l3evpn_1", Ip4Address::from_string("1.1.1.10"), 32,
                    "vnet10", true, "vn1");
    ValidateRouting("l3evpn_1", Ip4Address::from_string("1.1.1.11"), 32,
                    "vnet11", true, "vn1");
    ValidateRouting("l3evpn_1", Ip4Address::from_string("2.2.2.20"), 32,
                    "vnet20", true, "vn2");
    // validate subnet route for vn2 gets added to vrf1 inet table
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("2.2.2.0"), 24, true);
    // validate subnet route for vn1 gets added to vrf2 inet table
    ValidateBridge("vrf2", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.0"), 24, true);
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.10"), 32, true);
    ValidateBridge("vrf1", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.11"), 32, true);
    ValidateBridge("vrf2", "l3evpn_1",
                   Ip4Address::from_string("2.2.2.20"), 32, true);

    // Add one subnet to existing ipam default-network-ipam,vn1
    IpamInfo ipam_update[] = {
        {"1.1.1.0", 24, "1.1.1.200", true},
        {"3.3.3.0", 24, "3.3.3.300", true},
    };
    AddIPAM("vn1", ipam_update, 2);
    client->WaitForIdle();

    // Validate both subnet routes for vn1 in vn2
    ValidateBridge("vrf2", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.0"), 24, true);
    ValidateBridge("vrf2", "l3evpn_1",
                   Ip4Address::from_string("3.3.3.0"), 24, true);

    // Delete 3.3.3.0/24 subnet from ipam default-network-ipam,vn1
    AddIPAM("vn1", ipam_1, 1);
    client->WaitForIdle();
    // Validate vn2 has subnet route only for 1.1.10/24 and not 3.3.3.0/24
    ValidateBridge("vrf2", "l3evpn_1",
                   Ip4Address::from_string("1.1.1.0"), 24, true);
    InetUnicastRouteEntry *rt =
        RouteGet("vrf2", Ip4Address::from_string("3.3.3.0"), 24);
    EXPECT_TRUE(rt == NULL);

    DelIPAM("vn1");
    client->WaitForIdle();

    // Verify both subnet routes for vn1 get deleted in vrf2 inet table
    InetUnicastRouteEntry *rt_sub_1 =
        RouteGet("vrf2", Ip4Address::from_string("1.1.1.0"), 24);
    EXPECT_TRUE(rt_sub_1 == NULL);
    InetUnicastRouteEntry *rt_sub_2 =
        RouteGet("vrf2", Ip4Address::from_string("3.3.3.0"), 24);
    EXPECT_TRUE(rt_sub_2 == NULL);
    client->WaitForIdle();
    DeleteEnvironment(true);
}

int main(int argc, char *argv[]) {
    ::testing::InitGoogleTest(&argc, argv);
    GETUSERARGS();
    strcpy(init_file, DEFAULT_VNSW_CONFIG_FILE);
    client = TestInit(init_file, ksync_init, true, false);
    int ret = RUN_ALL_TESTS();
    TestShutdown();
    return ret;
}
