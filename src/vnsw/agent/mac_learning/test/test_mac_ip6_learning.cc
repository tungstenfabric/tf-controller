/*
 * Copyright (c) 2017 Juniper Networks, Inc. All rights reserved.
 */

#include "base/os.h"
#include "base/address_util.h"
#include "testing/gunit.h"
#include <sys/socket.h>
#include <netinet/if_ether.h>
#include <base/logging.h>

#include <io/event_manager.h>
#include <cmn/agent_cmn.h>
#include <oper/operdb_init.h>
#include <controller/controller_init.h>
#include <controller/controller_vrf_export.h>
#include <pkt/pkt_init.h>
#include <services/services_init.h>
#include <vrouter/ksync/ksync_init.h>
#include <oper/vrf.h>
#include <pugixml/pugixml.hpp>
#include <services/arp_proto.h>
#include <test/test_cmn_util.h>
#include <test/pkt_gen.h>
#include "vr_types.h"
#include <services/services_sandesh.h>
#include "mac_learning/mac_learning_proto.h"
#include "mac_learning/mac_learning_mgmt.h"
#include "mac_learning/mac_learning_init.h"
#include "mac_learning/mac_ip_learning.h"

// Create vm-port and vn
struct PortInfo input[] = {
    {"vnet1", 1, "8.1.1.1", "00:00:00:01:01:01", 1, 1, "fd11::2"},
};

IpamInfo ipam_info[] = {
    {"fd11::", 120, "fd11::1"},
};

class MacIp6LearningTest : public ::testing::Test {
public:
    MacIp6LearningTest() {
        agent_ = Agent::GetInstance();
    };

    virtual void SetUp() {
        CreateV6VmportEnv(input, 1);
        client->WaitForIdle();
        EXPECT_TRUE(VmPortActive(1));
        AddIPAM("vn1", ipam_info, 1);
        EnableMacIpLearningVnConfig("vn1", 1, true);
        client->WaitForIdle();
    }

    virtual void TearDown() {
        DeleteVmportEnv(input, 1, true, 0, NULL, NULL, true, true);
        client->WaitForIdle();
        EXPECT_FALSE(VmPortFindRetDel(1));
        EXPECT_FALSE(VrfFind("vrf1", true));
        client->WaitForIdle();
        DelIPAM("vn1");
        client->WaitForIdle();
    }
protected:
    Agent *agent_;
};

void TxL2Packet(int ifindex, const char *smac, const char *dmac,
                const char *sip, const char *dip,
                int proto, int vrf,
                uint16_t sport, uint16_t dport) {
    PktGen *pkt = new PktGen();

    pkt->AddEthHdr("00:00:00:00:00:01", "00:00:00:00:00:02", 0x800);
    pkt->AddAgentHdr(ifindex, AgentHdr::TRAP_MAC_IP_LEARNING, 0,  vrf) ;
    pkt->AddEthHdr(dmac, smac, ETHERTYPE_IPV6);
    pkt->AddIp6Hdr(sip, dip, proto);
    if (proto == IPPROTO_ICMPV6) {
        pkt->AddIcmp6Hdr();
    } else if (proto == IPPROTO_UDP) {
        pkt->AddUdpHdr(sport, dport, 64);
    }
    uint8_t *ptr(new uint8_t[pkt->GetBuffLen()]);
    memcpy(ptr, pkt->GetBuff(), pkt->GetBuffLen());
    client->agent_init()->pkt0()->ProcessFlowPacket(ptr, pkt->GetBuffLen(),
            pkt->GetBuffLen());
    delete pkt;
}

// send trap for map ip learning and verify learnt routes
TEST_F(MacIp6LearningTest, Test1) {
    const VmInterface *intf = static_cast<const VmInterface *>(VmPortGet(1));
    TxL2Packet(intf->id(), "00:00:00:11:22:33", "00:00:00:33:22:11",
               "fd11::5", "fd11::1", 58, intf->vrf()->vrf_id(), 1, 1);
    client->WaitForIdle();
    boost::system::error_code error_code;
    Ip6Address sip = Ip6Address::from_string("fd11::5", error_code);
    MacAddress smac(0x00, 0x00, 0x00, 0x11, 0x22, 0x33);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, IpAddress(), 0) != NULL);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, AddressFromString("fd11::5", &error_code), 0) != NULL);
    EXPECT_TRUE(L2RouteGet("vrf1", smac) != NULL);
    EXPECT_TRUE(RouteGetV6("vrf1", sip, 128) != NULL);
    const InterfaceNH *nh  =
        dynamic_cast<const InterfaceNH *>(L2RouteToNextHop("vrf1", smac));
    EXPECT_TRUE(nh->GetDMac() == smac);
    EXPECT_TRUE(nh->PolicyEnabled());
    nh = dynamic_cast<const InterfaceNH *>(RouteGetV6("vrf1", sip, 128)->GetActiveNextHop());
    EXPECT_TRUE(nh->GetDMac() == smac);
    EXPECT_TRUE(nh->PolicyEnabled());

    VmInterface::Delete(Agent::GetInstance()->interface_table(),
                         MakeUuid(1), VmInterface::INSTANCE_MSG);
    client->WaitForIdle();
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, IpAddress(), 0) == NULL);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, AddressFromString("fd11::5", &error_code), 0) == NULL);
    EXPECT_TRUE(L2RouteGet("vrf1", smac) == NULL);
    EXPECT_TRUE(RouteGetV6("vrf1", sip, 128) == NULL);
}

// if target IP is unreachable , verify that routes of target IP are deleted.
TEST_F(MacIp6LearningTest, Test2) {
    const VmInterface *intf = static_cast<const VmInterface *>(VmPortGet(1));
    TxL2Packet(intf->id(), "00:00:00:11:22:33", "00:00:00:33:22:11",
               "fd11::5", "fd11::1", 58, intf->vrf()->vrf_id(), 1, 1);
    client->WaitForIdle();
    boost::system::error_code error_code;
    Ip6Address sip_v6 = Ip6Address::from_string("fd11::5", error_code);
    MacAddress smac(0x00, 0x00, 0x00, 0x11, 0x22, 0x33);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, IpAddress(), 0) != NULL);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, AddressFromString("fd11::5", &error_code), 0) != NULL);
    EXPECT_TRUE(L2RouteGet("vrf1", smac) != NULL);
    EXPECT_TRUE(RouteGetV6("vrf1", sip_v6, 128) != NULL);
    IpAddress sip = IpAddress::from_string("fd11::5");
    agent_->mac_learning_proto()->GetMacIpLearningTable()->
                MacIpEntryUnreachable(GetVrfId("vrf1"), sip, smac);
    client->WaitForIdle();
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, IpAddress(), 0) == NULL);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, AddressFromString("fd11::5", &error_code), 0) == NULL);
    EXPECT_TRUE(L2RouteGet("vrf1", smac) == NULL);
    EXPECT_TRUE(RouteGetV6("vrf1", sip_v6, 128) == NULL);

}

// Detect local IP move, verify that old mac routes are deleted
// // and new mac routes are added.
TEST_F(MacIp6LearningTest, Test3) {
    const VmInterface *intf = static_cast<const VmInterface *>(VmPortGet(1));
    TxL2Packet(intf->id(), "00:00:00:11:22:33", "00:00:00:33:22:11",
               "fd11::5", "fd11::1", 58, intf->vrf()->vrf_id(), 1, 1);
    client->WaitForIdle();
    boost::system::error_code error_code;
    Ip6Address sip = Ip6Address::from_string("fd11::5", error_code);
    MacAddress smac_old(0x00, 0x00, 0x00, 0x11, 0x22, 0x33);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac_old, IpAddress(), 0) != NULL);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac_old, AddressFromString("fd11::5", &error_code), 0) != NULL);
    EXPECT_TRUE(L2RouteGet("vrf1", smac_old) != NULL);
    EXPECT_TRUE(RouteGetV6("vrf1", sip, 128) != NULL);
    EXPECT_TRUE(agent_->mac_learning_proto()->GetMacIpLearningTable()->
            GetPairedMacAddress(intf->vrf()->vrf_id(), sip) == smac_old);
    MacAddress smac_new(0x00, 0x00, 0x00, 0x11, 0x22, 0x44);
    TxL2Packet(intf->id(), "00:00:00:11:22:44", "00:00:00:33:22:11",
               "fd11::5", "fd11::1", 58, intf->vrf()->vrf_id(), 1, 1);
    client->WaitForIdle();
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac_new, IpAddress(), 0) != NULL);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac_new, AddressFromString("fd11::5", &error_code), 0) != NULL);
    EXPECT_TRUE(L2RouteGet("vrf1", smac_new) != NULL);
    EXPECT_TRUE(agent_->mac_learning_proto()->GetMacIpLearningTable()->
            GetPairedMacAddress(intf->vrf()->vrf_id(), sip) == smac_new);
    const InterfaceNH *nh  =
        dynamic_cast<const InterfaceNH *>(L2RouteToNextHop("vrf1", smac_new));
    EXPECT_TRUE(nh->GetDMac() == smac_new);
    EXPECT_TRUE(nh->PolicyEnabled());
    nh = dynamic_cast<const InterfaceNH *>(RouteGetV6("vrf1", sip, 128)->GetActiveNextHop());
    EXPECT_TRUE(nh->GetDMac() == smac_new);
    EXPECT_TRUE(nh->PolicyEnabled());
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac_old, IpAddress(), 0) == NULL);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac_old, AddressFromString("fd11::5", &error_code), 0) == NULL);
    EXPECT_TRUE(L2RouteGet("vrf1", smac_old) == NULL);
}

// detect remote IP move, verify that locally generated routes are deleted.
TEST_F(MacIp6LearningTest, Test4) {
    BgpPeer *bgp_peer = CreateBgpPeer("127.0.0.1", "remote");
    const VmInterface *intf = static_cast<const VmInterface *>(VmPortGet(1));
    TxL2Packet(intf->id(), "00:00:00:11:22:33", "00:00:00:33:22:11",
               "fd11::5", "fd11::1", 58, intf->vrf()->vrf_id(), 1, 1);
    client->WaitForIdle();
    boost::system::error_code error_code;
    Ip6Address sip = Ip6Address::from_string("fd11::5", error_code);
    MacAddress smac_old(0x00, 0x00, 0x00, 0x11, 0x22, 0x33);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac_old, IpAddress(), 0) != NULL);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac_old, AddressFromString("fd11::5", &error_code), 0) != NULL);
    EXPECT_TRUE(L2RouteGet("vrf1", smac_old) != NULL);
    EXPECT_TRUE(RouteGetV6("vrf1", sip, 128) != NULL);
    MacAddress smac_new(0x00, 0x00, 0x00, 0x11, 0x22, 0x44);
    BridgeTunnelRouteAdd(bgp_peer, "vrf1", TunnelType::AllType(),
            Ip4Address::from_string("10.10.10.10"),
                         (MplsTable::kStartLabel + 60), smac_new,
                         Ip6Address::from_string("fd11::5"), 128);
    client->WaitForIdle();
    EXPECT_TRUE(L2RouteGet("vrf1", smac_new) != NULL);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac_old, IpAddress(), 0) == NULL);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac_old, AddressFromString("fd11::5", &error_code), 0) == NULL);
    EXPECT_TRUE(L2RouteGet("vrf1", smac_old) == NULL);
    EXPECT_TRUE(RouteGetV6("vrf1", sip, 128) != NULL);
    EvpnAgentRouteTable::DeleteReq(bgp_peer, "vrf1", smac_new,
                                   Ip6Address::from_string("fd11::5"), 128, 0,
                                   (new ControllerVmRoute(bgp_peer)));
    client->WaitForIdle();
    DeleteBgpPeer(bgp_peer);
    client->WaitForIdle();
}

// enable/disable policy and verify that bridge and inet routes
// // point to nh with polciy enabled/disabled respectively.
TEST_F(MacIp6LearningTest, Test5) {
    const VmInterface *intf = static_cast<const VmInterface *>(VmPortGet(1));
    TxL2Packet(intf->id(), "00:00:00:11:22:33", "00:00:00:33:22:11",
               "fd11::5", "fd11::1", 58, intf->vrf()->vrf_id(), 1, 1);
    client->WaitForIdle();
    boost::system::error_code error_code;
    DisableInterfacePolicy(input[0].name, input[0].intf_id, true);
    client->WaitForIdle();
    Ip6Address sip = Ip6Address::from_string("fd11::5", error_code);
    MacAddress smac(0x00, 0x00, 0x00, 0x11, 0x22, 0x33);
    const InterfaceNH *nh  =
        dynamic_cast<const InterfaceNH *>(L2RouteToNextHop("vrf1", smac));
    EXPECT_TRUE(nh->GetDMac() == smac);
    EXPECT_FALSE(nh->PolicyEnabled());
    nh = dynamic_cast<const InterfaceNH *>(RouteGetV6("vrf1", sip, 128)->GetActiveNextHop());
    EXPECT_TRUE(nh->GetDMac() == smac);
    EXPECT_FALSE(nh->PolicyEnabled());
    DisableInterfacePolicy(input[0].name, input[0].intf_id, false);
    client->WaitForIdle();
    nh  = dynamic_cast<const InterfaceNH *>(L2RouteToNextHop("vrf1", smac));
    EXPECT_TRUE(nh->GetDMac() == smac);
    EXPECT_TRUE(nh->PolicyEnabled());
    nh = dynamic_cast<const InterfaceNH *>(RouteGetV6("vrf1", sip, 128)->GetActiveNextHop());
    EXPECT_TRUE(nh->GetDMac() == smac);
    EXPECT_TRUE(nh->PolicyEnabled());

}

// verify learnt routes with forwarding mode as L2 only
// and L2/L3
TEST_F(MacIp6LearningTest, Test6) {
    const VmInterface *intf = static_cast<const VmInterface *>(VmPortGet(1));
    TxL2Packet(intf->id(), "00:00:00:11:22:33", "00:00:00:33:22:11",
               "fd11::5", "fd11::1", 58, intf->vrf()->vrf_id(), 1, 1);
    client->WaitForIdle();
    boost::system::error_code error_code;
    Ip6Address sip = Ip6Address::from_string("fd11::5", error_code);
    MacAddress smac(0x00, 0x00, 0x00, 0x11, 0x22, 0x33);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, IpAddress(), 0) != NULL);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, AddressFromString("fd11::5", &error_code), 0) != NULL);
    EXPECT_TRUE(RouteGetV6("vrf1", sip, 128) != NULL);
    EXPECT_TRUE(L2RouteGet("vrf1", smac) != NULL);
    ModifyForwardingModeVn("vn1", 1, "l2");
    client->WaitForIdle();
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, IpAddress(), 0) != NULL);
    EXPECT_FALSE(EvpnRouteGet("vrf1", smac, AddressFromString("fd11::5", &error_code), 0) != NULL);
    EXPECT_TRUE(L2RouteGet("vrf1", smac) != NULL);
    EXPECT_FALSE(RouteGetV6("vrf1", sip, 128) != NULL);
    ModifyForwardingModeVn("vn1", 1, "l2_l3");
    client->WaitForIdle();
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, IpAddress(), 0) != NULL);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, AddressFromString("fd11::5", &error_code), 0) != NULL);
    EXPECT_TRUE(L2RouteGet("vrf1", smac) != NULL);
    EXPECT_TRUE(RouteGetV6("vrf1", sip, 128) != NULL);
}

// verify that learnt routes are deleted when interface is admin down
TEST_F(MacIp6LearningTest, Test7) {
    const VmInterface *intf = static_cast<const VmInterface *>(VmPortGet(1));
    TxL2Packet(intf->id(), "00:00:00:11:22:33", "00:00:00:33:22:11",
               "fd11::5", "fd11::1", 58, intf->vrf()->vrf_id(), 1, 1);
    client->WaitForIdle();
    boost::system::error_code error_code;
    Ip6Address sip =  Ip6Address::from_string("fd11::5", error_code);
    MacAddress smac(0x00, 0x00, 0x00, 0x11, 0x22, 0x33);
    EXPECT_TRUE(intf->learnt_mac_ip_list().list_.size()  == 1);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, IpAddress(), 0) != NULL);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, AddressFromString("fd11::5", &error_code), 0) != NULL);
    EXPECT_TRUE(L2RouteGet("vrf1", smac) != NULL);
    EXPECT_TRUE(RouteGetV6("vrf1", sip, 128) != NULL);
    ModifyInterfaceAdminState(input[0].name, input[0].intf_id, false);
    client->WaitForIdle();
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, IpAddress(), 0) == NULL);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, AddressFromString("fd11::5", &error_code), 0) == NULL);
    EXPECT_TRUE(L2RouteGet("vrf1", smac) == NULL);
    EXPECT_TRUE(RouteGetV6("vrf1", sip, 128) == NULL);
    EXPECT_TRUE(intf->learnt_mac_ip_list().list_.size()  == 0);
}

int main(int argc, char *argv[]) {
    GETUSERARGS();
    client = TestInit(init_file, ksync_init);
    int ret = RUN_ALL_TESTS();
    TestShutdown();
    return ret;
}
