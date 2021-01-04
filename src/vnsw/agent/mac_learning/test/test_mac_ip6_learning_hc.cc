/*
 * Copyright (c) 2013 Juniper Networks, Inc. All rights reserved.
 */


#include "base/os.h"
#include "testing/gunit.h"
#include <boost/assign.hpp>

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
#include <oper/mirror_table.h>
#include <pugixml/pugixml.hpp>
#include <services/icmpv6_proto.h>
#include <vr_interface.h>
#include <test/pkt_gen.h>
#include <test/test_cmn_util.h>
#include "vr_types.h"
#include "xmpp/test/xmpp_test_util.h"
#include <services/services_sandesh.h>
#include "oper/path_preference.h"
#include "services/ndp_entry.h"
#include "mac_learning/mac_learning_proto.h"
#include "mac_learning/mac_learning_mgmt.h"
#include "mac_learning/mac_learning_init.h"

using namespace std;
using namespace boost::assign;
using namespace boost::posix_time;

struct PortInfo input1[] = {
    {"vnet1", 1, "8.1.1.1", "00:00:00:01:01:01", 1, 1, "fd11::2"},
    {"vnet2", 2, "8.1.1.2", "00:00:01:01:01:02", 1, 1, "fd11::3"}
};

IpamInfo ipam_info[] = {
    {"fd11::", 120, "fd11::1"},
};

MacAddress src_mac(0x00, 0x01, 0x02, 0x03, 0x04, 0x05);
MacAddress dest_mac(0x00, 0x01, 0x02, 0x03, 0x04, 0x05);

class MacIp6LearningHCTest : public ::testing::Test {
protected:
    MacIp6LearningHCTest() {
        disable_na = false;
        TestPkt0Interface *tap = (TestPkt0Interface *)
                    (Agent::GetInstance()->pkt()->control_interface());
        tap->RegisterCallback(
                boost::bind(&MacIp6LearningHCTest::Pkt0IntfReceiveIPv6NS, this, _1, _2));
   }

    uint32_t Sum(uint16_t *ptr, std::size_t len, uint32_t sum) {
        while (len > 1) {
            sum += *ptr++;
            len -= 2;
            if (sum & 0x80000000)
                sum = (sum & 0xFFFF) + (sum >> 16);
        }

        if (len > 0)
            sum += *(uint8_t *)ptr;

        return sum;
    }

    uint16_t Csum(uint16_t *ptr, std::size_t len, uint32_t sum) {
        sum = Sum(ptr, len, sum);

        while (sum >> 16)
            sum = (sum & 0xFFFF) + (sum >> 16);

        return ~sum;
    }

    void SendND(short ifindex, short vrf, uint8_t *sip, uint8_t *tip,
                bool ns = true, bool solicit = false) {
        int len = ICMP_PKT_SIZE;
        uint8_t *ptr(new uint8_t[len]);
        uint8_t *buf  = ptr;
        memset(buf, 0, len);

        struct ether_header *eth = (struct ether_header *)buf;
        eth->ether_dhost[5] = 1;
        eth->ether_shost[5] = 2;
        eth->ether_type = htons(0x800);

        agent_hdr *agent = (agent_hdr *)(eth + 1);
        agent->hdr_ifindex = htons(ifindex);
        agent->hdr_vrf = htons(vrf);
        agent->hdr_cmd = htons(AgentHdr::TRAP_RESOLVE);

        eth = (struct ether_header *) (agent + 1);
        dest_mac.ToArray(eth->ether_dhost, sizeof(eth->ether_dhost));
        src_mac.ToArray(eth->ether_shost, sizeof(eth->ether_shost));
        eth->ether_type = htons(ETHERTYPE_IPV6);

        ip6_hdr *ip6 = (ip6_hdr *) (eth + 1);
        ip6->ip6_flow = htonl(0x60000000); // version 6, TC and Flow set to 0
        ip6->ip6_plen = htons(64);
        ip6->ip6_nxt = IPPROTO_ICMPV6;
        ip6->ip6_hlim = 16;
        memcpy(ip6->ip6_src.s6_addr, sip, 16);

        uint8_t *icmp;
        if (ns) {
            nd_neighbor_solicit *ns = (nd_neighbor_solicit *) (ip6 + 1);
            ns->nd_ns_type = ND_NEIGHBOR_SOLICIT;
            ns->nd_ns_code = 0;
            ns->nd_ns_reserved = 0;
            memcpy(ns->nd_ns_target.s6_addr, tip, 16);
            uint16_t offset = sizeof(nd_neighbor_solicit);
            dest_mac.ToArray(((uint8_t *)ns) + offset, sizeof(eth->ether_dhost));
        } else {
            nd_neighbor_advert *na = (nd_neighbor_advert *) (ip6 + 1);
            na->nd_na_type = ND_NEIGHBOR_ADVERT;
            na->nd_na_code = 0;
            na->nd_na_flags_reserved = ND_NA_FLAG_OVERRIDE;
            if (solicit)
                na->nd_na_flags_reserved = ND_NA_FLAG_SOLICITED;
            memcpy(na->nd_na_target.s6_addr, tip, 16);
            uint16_t offset = sizeof(nd_neighbor_advert);
            nd_opt_hdr *opt = (nd_opt_hdr *) (((uint8_t *)na) + offset);
            opt->nd_opt_type = ND_OPT_TARGET_LINKADDR;
            opt->nd_opt_len = 1;
            offset += sizeof(nd_opt_hdr);
            dest_mac.ToArray(((uint8_t *)na) + offset, sizeof(eth->ether_dhost));
        }
        uint32_t plen = htonl((uint32_t)64);
        uint32_t next = htonl((uint32_t)IPPROTO_ICMPV6);
        uint32_t pseudo = 0;
        pseudo = Sum((uint16_t *)sip, 16, 0);
        pseudo = Sum((uint16_t *)&plen, 4, pseudo);
        pseudo = Sum((uint16_t *)&next, 4, pseudo);
        if (ns) {
            nd_neighbor_solicit *icmp = (nd_neighbor_solicit *)(ip6 + 1);
            icmp->nd_ns_cksum = Csum((uint16_t *)icmp, 64, pseudo);
        } else {
            nd_neighbor_advert *icmp = (nd_neighbor_advert *)(ip6 + 1);
            icmp->nd_na_cksum = Csum((uint16_t *)icmp, 64, pseudo);
        }

        TestPkt0Interface *tap = (TestPkt0Interface *)
                (Agent::GetInstance()->pkt()->control_interface());
        tap->TxPacket(ptr, len);
    }

    void SendNA(short ifindex, short vrf, uint8_t *sip, uint8_t *tip,
                bool solicit = false) {
        return SendND(ifindex, vrf, sip, tip, false, solicit);
    }

    virtual void SetUp() {
        agent_ = Agent::GetInstance();
        CreateV6VmportEnv(input1, 2);
        client->WaitForIdle();
        EXPECT_TRUE(VmPortActive(1));
        EXPECT_TRUE(VmPortActive(2));
        AddIPAM("vn1", ipam_info, 1);
        client->WaitForIdle();
    }

    virtual void TearDown() {
        DeleteVmportEnv(input1, 2, true, 0, NULL, NULL, true, true);
        client->WaitForIdle();
        DelIPAM("vn1");
        client->WaitForIdle();
        EXPECT_TRUE(VrfGet("vrf1", true) == NULL);
    }

    void Pkt0IntfReceiveIPv6NS(uint8_t *buf, std::size_t len) {
        #define IP6_ICMPV6TYPE  58
        struct ether_header *eth = (struct ether_header *)buf;
        agent_hdr *agent = (agent_hdr *)(eth + 1);
        eth = (struct ether_header *) (agent + 1);
        if (ntohs(eth->ether_type) == ETHERTYPE_IPV6) {
            struct ip6_hdr *ip6 = (struct ip6_hdr *) (eth + 1);
            if (ip6->ip6_nxt == IP6_ICMPV6TYPE) {
                nd_neighbor_solicit *nshdr = (nd_neighbor_solicit *) (ip6 + 1);
                if (nshdr->nd_ns_hdr.icmp6_type == ND_NEIGHBOR_SOLICIT) {
                    if(!disable_na){
                    // Sending NA from interface instead of using multicast addr
                    uint8_t target[16] = {0xfd, 0x11, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0};
                    target[15] = ip6->ip6_dst.s6_addr[15];
                    SendNA(ntohs(agent->hdr_ifindex), ntohs(agent->hdr_vrf),
                      ip6->ip6_src.s6_addr, target, true);
                    }
                }
            }
        }
    }
    bool disable_na;
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

TEST_F(MacIp6LearningHCTest, NSTest1) {
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
    sleep(20);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, AddressFromString("fd11::5", &error_code), 0) != NULL);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, IpAddress(), 0) != NULL);
}

TEST_F(MacIp6LearningHCTest, NSTest2) {
    disable_na = true;
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
    sleep(20);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, AddressFromString("fd11::5", &error_code), 0) == NULL);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, IpAddress(), 0) == NULL);
}

// Create BFD Health and attach to the virtual-network
// Modify the health check
// Health check parameters should reflect in MAC IP learning entry
TEST_F(MacIp6LearningHCTest, BfdTest1) {
    const VmInterface *intf = static_cast<const VmInterface *>(VmPortGet(1));
    TxL2Packet(intf->id(), "00:00:00:11:22:30", "00:00:00:11:22:31",
                "fd11::5", "fd11::1", 58, intf->vrf()->vrf_id(), 1, 1);
    client->WaitForIdle();

    intf = static_cast<const VmInterface *>(VmPortGet(2));
    TxL2Packet(intf->id(), "00:00:00:11:22:31", "00:00:00:11:22:30",
                "fd11::1", "fd11::5", 58, intf->vrf()->vrf_id(), 1, 1);
    client->WaitForIdle();

    boost::system::error_code ec;

    AddVnHealthCheckService("HC-1", 1, 1, 1, 3, true, NULL, 0);
    AddLink("virtual-network", "vn1",
            "service-health-check", "HC-1");
    client->WaitForIdle();

    AddVnHealthCheckService("HC-1", 1, 1, 1, 3, true, NULL, 0);
    client->WaitForIdle();

    AddVnHealthCheckService("HC-1", 1, 2, 5, 3, true, NULL, 0);
    client->WaitForIdle();

    IpAddress ip = IpAddress(Ip6Address::from_string("fd11::5", ec));
    MacIpLearningKey key(GetVrfId("vrf1"), ip);
    MacIpLearningEntry *entry = agent_->mac_learning_proto()->
                GetMacIpLearningTable()->Find(key);
    EXPECT_TRUE(entry != NULL);
    EXPECT_TRUE(entry->HcService() != NULL);
    EXPECT_TRUE(entry->HcService()->name() == "HC-1");
    EXPECT_TRUE(entry->HcInstance() != NULL);

    ip = IpAddress(Ip6Address::from_string("fd11::1", ec));
    MacIpLearningKey key1(GetVrfId("vrf1"), ip);
    entry = agent_->mac_learning_proto()->
                GetMacIpLearningTable()->Find(key1);
    EXPECT_TRUE(entry != NULL);

    DelLink("virtual-network", "vn1",
            "service-health-check", "HC-1");
    client->WaitForIdle();
    DelHealthCheckService("HC-1");
    client->WaitForIdle();
}

// Create and attach BFD health check to VN
// Modify HC to take varying ip address (toggle from ALL)
TEST_F(MacIp6LearningHCTest, BfdTest2) {

    const VmInterface *intf = static_cast<const VmInterface *>(VmPortGet(1));
    boost::system::error_code ec;

    intf = static_cast<const VmInterface *>(VmPortGet(2));
    TxL2Packet(intf->id(), "00:00:00:11:22:31", "00:00:00:11:22:30",
                "fd11::5", "fd11::1", 58, intf->vrf()->vrf_id(), 1, 1);
    client->WaitForIdle();

    AddVnHealthCheckService("HC-1", 1, 1, 1, 3, true, NULL, 0);
    AddLink("virtual-network", "vn1",
            "service-health-check", "HC-1");
    client->WaitForIdle();

    IpStr ip_list[2] = {"fd11::5", "fd11::1"};
    AddVnHealthCheckService("HC-1", 1, 1, 1, 3, false, ip_list, 2);
    client->WaitForIdle();

    IpStr ip_list1[3] = {"fd11::5", "fd11::1", "fd11::6"};
    AddVnHealthCheckService("HC-1", 1, 1, 1, 3, false, ip_list1, 3);
    client->WaitForIdle();

    IpAddress ip = IpAddress(Ip6Address::from_string("fd11::5", ec));
    MacIpLearningKey key(GetVrfId("vrf1"), ip);
    MacIpLearningEntry *entry = agent_->mac_learning_proto()->
                GetMacIpLearningTable()->Find(key);
    EXPECT_TRUE(entry != NULL);
    EXPECT_TRUE(entry->HcService() != NULL);
    EXPECT_TRUE(entry->HcService()->name() == "HC-1");
    EXPECT_TRUE(entry->HcInstance() != NULL);

    sleep(3);

    entry = agent_->mac_learning_proto()->
                GetMacIpLearningTable()->Find(key);
    EXPECT_TRUE(entry != NULL);

    DelLink("virtual-network", "vn1",
            "service-health-check", "HC-1");
    client->WaitForIdle();
    DelHealthCheckService("HC-1");
    client->WaitForIdle();
}

// Attach BFD HC and detach BFD HC and check in MAC IP learning entry
TEST_F(MacIp6LearningHCTest, BfdTest3) {

    boost::system::error_code ec;

    const VmInterface *intf = static_cast<const VmInterface *>(VmPortGet(1));
    TxL2Packet(intf->id(), "00:00:00:11:22:31", "00:00:00:11:22:30",
               "fd11::5", "fd11::1", 58, intf->vrf()->vrf_id(), 1, 1);
    client->WaitForIdle();

    AddVnHealthCheckService("HC-1", 1, 1, 1, 3, true, NULL, 0);
    AddLink("virtual-network", "vn1",
            "service-health-check", "HC-1");
    client->WaitForIdle();

    IpAddress ip = IpAddress(Ip6Address::from_string("fd11::5", ec));
    MacIpLearningKey key(GetVrfId("vrf1"), ip);
    MacIpLearningEntry *entry = agent_->mac_learning_proto()->
                GetMacIpLearningTable()->Find(key);
    EXPECT_TRUE(entry != NULL);
    EXPECT_TRUE(entry->HcService() != NULL);
    EXPECT_TRUE(entry->HcService()->name() == "HC-1");
    EXPECT_TRUE(entry->HcInstance() != NULL);

    DelHealthCheckService("HC-1");
    client->WaitForIdle();
    DelLink("virtual-network", "vn1",
            "service-health-check", "HC-1");
    client->WaitForIdle();

    ip = IpAddress(Ip6Address::from_string("fd11::5", ec));
    MacIpLearningKey key2(GetVrfId("vrf1"), ip);
    entry = agent_->mac_learning_proto()->
                GetMacIpLearningTable()->Find(key2);
    EXPECT_TRUE(entry != NULL);
    EXPECT_TRUE(entry->HcService() == NULL);
    EXPECT_TRUE(entry->HcInstance() == NULL);
}

// Attach BFD HC, change IP address list to have learnt IP
// and then delete IP address from list for BFD HC
TEST_F(MacIp6LearningHCTest, BfdTest4) {

    boost::system::error_code ec;

    const VmInterface *intf = static_cast<const VmInterface *>(VmPortGet(1));
    TxL2Packet(intf->id(), "00:00:00:11:22:31", "00:00:00:11:22:30",
                "fd11::5", "fd11::1", 58, intf->vrf()->vrf_id(), 1, 1);
    client->WaitForIdle();

    AddVnHealthCheckService("HC-1", 1, 1, 1, 3, true, NULL, 0);
    AddLink("virtual-network", "vn1",
            "service-health-check", "HC-1");
    client->WaitForIdle();

    IpStr ip_list[2] = {"fd11::5","fd11::1"};
    AddVnHealthCheckService("HC-1", 1, 1, 1, 3, false, ip_list, 2);
    client->WaitForIdle();

    IpAddress ip = IpAddress(Ip6Address::from_string("fd11::5", ec));
    MacIpLearningKey key(GetVrfId("vrf1"), ip);
    MacIpLearningEntry *entry = agent_->mac_learning_proto()->
                GetMacIpLearningTable()->Find(key);
    EXPECT_TRUE(entry != NULL);
    EXPECT_TRUE(entry->HcService() != NULL);
    EXPECT_TRUE(entry->HcService()->name() == "HC-1");
    EXPECT_TRUE(entry->HcInstance() != NULL);

    IpStr ip_list1[1] = {"fd11::1"};
    AddVnHealthCheckService("HC-1", 1, 1, 1, 3, false, ip_list1, 1);
    client->WaitForIdle();

    ip = IpAddress(Ip6Address::from_string("fd11::5", ec));
    MacIpLearningKey key2(GetVrfId("vrf1"), ip);
    entry = agent_->mac_learning_proto()->
                GetMacIpLearningTable()->Find(key2);
    EXPECT_TRUE(entry != NULL);
    EXPECT_TRUE(entry->HcService() == NULL);
    EXPECT_TRUE(entry->HcInstance() == NULL);

    DelLink("virtual-network", "vn1",
            "service-health-check", "HC-1");
    client->WaitForIdle();
    DelHealthCheckService("HC-1");
    client->WaitForIdle();
}

// Move IP to another interface and check for HC
TEST_F(MacIp6LearningHCTest, BfdTest5) {

    const VmInterface *intf = static_cast<const VmInterface *>(VmPortGet(1));

    boost::system::error_code ec;

    AddVnHealthCheckService("HC-1", 1, 1, 1, 3, true, NULL, 0);
    AddLink("virtual-network", "vn1",
            "service-health-check", "HC-1");
    client->WaitForIdle();

    TxL2Packet(intf->id(), "00:00:00:11:22:31", "00:00:00:11:22:30",
               "fd11::5", "fd11::1", 58, intf->vrf()->vrf_id(), 1, 1);
    client->WaitForIdle();

    intf = static_cast<const VmInterface *>(VmPortGet(2));
    IpAddress ip = IpAddress(Ip6Address::from_string("fd11::5", ec));
    MacIpLearningKey key(GetVrfId("vrf1"), ip);
    MacIpLearningEntry *entry = agent_->mac_learning_proto()->
                GetMacIpLearningTable()->Find(key);
    EXPECT_TRUE(entry != NULL);
    EXPECT_TRUE(entry->HcService() != NULL);
    EXPECT_TRUE(entry->HcService()->name() == "HC-1");
    EXPECT_TRUE(entry->HcInstance() != NULL);

    sleep(3);

    intf = static_cast<const VmInterface *>(VmPortGet(2));
    TxL2Packet(intf->id(), "00:00:00:11:22:33", "00:00:00:11:22:30",
               "fd11::5", "fd11::1", 58, intf->vrf()->vrf_id(), 1, 1);
    client->WaitForIdle();

    entry = agent_->mac_learning_proto()->
                GetMacIpLearningTable()->Find(key);
    EXPECT_TRUE(entry != NULL);
    EXPECT_TRUE(entry->HcService() != NULL);
    EXPECT_TRUE(entry->HcService()->name() == "HC-1");
    EXPECT_TRUE(entry->HcInstance() != NULL);

    MacAddress smac(0x00, 0x00, 0x00, 0x11, 0x22, 0x33);
    EXPECT_TRUE(EvpnRouteGet("vrf1", smac, IpAddress(), 0) != NULL);
    client->WaitForIdle();

    DelLink("virtual-network", "vn1",
            "service-health-check", "HC-1");
    client->WaitForIdle();
    DelHealthCheckService("HC-1");
    client->WaitForIdle();
}

// verify that mac-ip are not learnt once limit is reached on interface
TEST_F(MacIp6LearningHCTest, scale_test) {
    const VmInterface *intf = static_cast<const VmInterface *>(VmPortGet(1));
    for ( int i = 1; i < VmInterface::kMaxMacIpLimit + 20; i++) {
        std::stringstream mac_str;
        std::stringstream ip_str;
        mac_str << "00:00:00:11:22:" << i+12;
        ip_str << "fd11::" << i+12;
        boost::system::error_code error_code;
        const string ip = ip_str.str();
        const string mac = mac_str.str();
        Ip6Address sip = Ip6Address::from_string(ip_str.str(), error_code);
        MacAddress smac(0x00, 0x00, 0x00, 0x11, 0x22, i+12);
        TxL2Packet(intf->id(), smac.ToString().c_str(), "00:00:00:33:22:11",
               sip.to_string().c_str(), "fd11::11", 58, intf->vrf()->vrf_id(), 1, 1);
        client->WaitForIdle();
        if ( i <= VmInterface::kMaxMacIpLimit) {
            EXPECT_TRUE(intf->learnt_mac_ip_list().list_.size()  == i);
            EXPECT_TRUE(EvpnRouteGet("vrf1", smac, IpAddress(), 0) != NULL);
            EXPECT_TRUE(EvpnRouteGet("vrf1", smac, sip, 0) != NULL);
            EXPECT_TRUE(L2RouteGet("vrf1", smac) != NULL);
            EXPECT_TRUE(RouteGetV6("vrf1", sip, 128) != NULL);
        } else {
            EXPECT_TRUE(intf->learnt_mac_ip_list().list_.size()
                    == VmInterface::kMaxMacIpLimit);
            EXPECT_TRUE(EvpnRouteGet("vrf1", smac, IpAddress(), 0) == NULL);
            EXPECT_TRUE(EvpnRouteGet("vrf1", smac, sip, 0) == NULL);
            EXPECT_TRUE(L2RouteGet("vrf1", smac) == NULL);
            EXPECT_TRUE(RouteGetV6("vrf1", sip, 128) == NULL);
        }
    }

}

int main(int argc, char **argv) {
    GETUSERARGS();

    client = TestInit(init_file, ksync_init, true, true);
    usleep(100000);
    client->WaitForIdle();

    int ret = RUN_ALL_TESTS();
    usleep(100000);
    client->WaitForIdle();
    TestShutdown();
    delete client;
    return ret;
}
