/*
 * Copyright (c) 2014 Juniper Networks, Inc. All rights reserved.
 */

#include "base/os.h"

#include <sys/types.h>
#include <sys/socket.h>
#include <net/if.h>
#include <netinet/if_ether.h>
#include <netinet/ip.h>
#include <netinet/in.h>
#include <netinet/icmp6.h>
#include <boost/scoped_array.hpp>
#include <boost/assign/list_of.hpp>

#ifdef __linux__
#include <linux/netlink.h>
#include <linux/if_tun.h>
#include <linux/if_packet.h>
#endif

#ifdef __FreeBSD__
#include <sys/sockio.h>
#include <ifaddrs.h>
#endif

#include "testing/gunit.h"

#include <base/logging.h>
#include <io/event_manager.h>
#include <tbb/task.h>
#include <base/task.h>

#include <cmn/agent_cmn.h>

#include "cfg/cfg_init.h"
#include "oper/operdb_init.h"
#include "controller/controller_init.h"
#include "pkt/pkt_init.h"
#include "services/services_init.h"
#include "vrouter/ksync/ksync_init.h"
#include "oper/interface_common.h"
#include "oper/nexthop.h"
#include "route/route.h"
#include "oper/vrf.h"
#include "oper/mpls.h"
#include "oper/vm.h"
#include "oper/vn.h"
#include "filter/acl.h"
#include "test/test_init.h"
#include "vr_types.h"
#include <controller/controller_export.h>
#include <ksync/ksync_sock_user.h>
#include "oper/path_preference.h"
#include "services/icmpv6_proto.h"

#include <pugixml/pugixml.hpp>
#include <xmpp/xmpp_init.h>
#include <oper/tunnel_nh.h>
#include <oper/inet_unicast_route.h>
#include <controller/controller_route_path.h>
#include <controller/controller_vrf_export.h>
#include <services/services_sandesh.h>
#include <vr_interface.h>

#include "test/test_cmn_util.h"
#include "test/pkt_gen.h"
#include "io/test/event_manager_test.h"
#include "xmpp/test/xmpp_test_util.h"
#include "control_node_mock.h"

#define DEFAULT_VNSW_IPV6_UNDERLAY_CONFIG_FILE "controller/src/vnsw/agent/test/vnswa_ipv6_underlay_cfg.ini"

#define TARGET_GW_IPV6                      ("2001::01")
#define TARGET_VHOST_IP6                    ("2001::03")
#define TARGET_RC_1_IPV6                    ("2001::04")
#define TARGET_RC_2_IPV6                    ("2001::05")
#define TARGET_RC_3_IPV6                    ("3001::05")

#define MAC_LEN 6
char src_mac[MAC_LEN] = { 0x00, 0x01, 0x02, 0x03, 0x04, 0x05 };
char dest_mac[MAC_LEN] = { 0x00, 0x11, 0x12, 0x13, 0x14, 0x15 };

MacAddress target_gw_mac("00:00:01:01:01:11");
MacAddress target_rc_1_mac("00:00:01:01:01:14");
MacAddress target_rc_2_mac("00:00:01:01:01:15");

static const int kControlNodes = 2;
EventManager cn_evm[kControlNodes];
ServerThread *cn_thread[kControlNodes];
test::ControlNodeMock *cn_bgp_peer[kControlNodes];

void RouterIdDepInit(Agent *agent) {
    Agent::GetInstance()->controller()->Connect();
}

class Ipv6UnderlayTest : public ::testing::Test {
public:
    virtual void SetUp() {
        agent_ = Agent::GetInstance();
        intf_count_ = agent_->interface_table()->Size();
        icmpv6_rx_count_ = 0;
        client->WaitForIdle();

        TestPkt0Interface *tap = (TestPkt0Interface *)
                    (Agent::GetInstance()->pkt()->control_interface());
        tap->RegisterCallback(
                boost::bind(&Ipv6UnderlayTest::IPv6TestClientReceive, this, _1, _2));

        for (uint32_t i = 0; i < kControlNodes; i++) {
            bgp_peer_[i] = agent_->controller_xmpp_channel(i)->bgp_peer_id();
        }
    }

    virtual void TearDown() {
        TestPkt0Interface *tap = (TestPkt0Interface *)
                    (Agent::GetInstance()->pkt()->control_interface());
        tap->RegisterCallback(
                boost::bind(&Ipv6UnderlayTest::DummyClientReceive, this, _1, _2));
        for (uint32_t i = 0; i < kControlNodes; i++) {
            cn_bgp_peer[i]->Clear();
        }

        client->WaitForIdle();
        WAIT_FOR(100, 1000, (agent_->interface_table()->Size() == intf_count_));
        WAIT_FOR(100, 1000, (agent_->vrf_table()->Size() == 2U));
        WAIT_FOR(100, 1000, (agent_->vm_table()->Size() == 0U));
        WAIT_FOR(100, 1000, (agent_->vn_table()->Size() == 0U));
    }

    BgpPeer *bgp_peer(uint32_t idx) {
        return bgp_peer_[idx];
    }

    void DummyClientReceive(uint8_t *buf, std::size_t len) {
        // IPv6TestClientReceive(buf, len);
    }

    void IPv6TestClientReceive(uint8_t *buf, std::size_t len) {
        struct ether_header *eth = (struct ether_header *)buf;

        agent_hdr *agent = (agent_hdr *)(eth + 1);

        eth = (struct ether_header *) (agent + 1);
        uint16_t *ptr = (uint16_t *) ((uint8_t*)eth + ETHER_ADDR_LEN * 2);
        uint16_t proto = ntohs(*ptr);

        if (proto == 0x86DD) {
            struct ip6_hdr *ip = (struct ip6_hdr *) (eth + 1);
            if (ip->ip6_ctlun.ip6_un1.ip6_un1_nxt == IPPROTO_ICMPV6) {
                nd_neighbor_solicit *icmp = (nd_neighbor_solicit *)(ip + 1);
                if (icmp->nd_ns_type != ND_NEIGHBOR_SOLICIT) {
                    return;
                }

                Ip6Address::bytes_type addr;
                for (int i = 0; i < 16; i++) {
                    addr[i] = icmp->nd_ns_target.s6_addr[i];
                }
                IpAddress ip_taddr = IpAddress(Ip6Address(addr));

                Ip6Address gw_addr = Ip6Address::from_string(TARGET_GW_IPV6);
                Ip6Address src_addr = gw_addr;
                Ip6Address dst_addr = Ip6Address::from_string(TARGET_VHOST_IP6);
                Ip6Address rc_1_addr = Ip6Address::from_string(TARGET_RC_1_IPV6);
                Ip6Address rc_2_addr = Ip6Address::from_string(TARGET_RC_2_IPV6);

                MacAddress target_mac_addr;
                if (ip_taddr == gw_addr) {
                    target_mac_addr = target_gw_mac;
                } else if (ip_taddr == rc_1_addr) {
                    target_mac_addr = target_rc_1_mac;
                } else if (ip_taddr == rc_2_addr) {
                    target_mac_addr = target_rc_2_mac;
                }

                SendNDAdvert(ntohs(agent->hdr_ifindex), src_addr, dst_addr, ip_taddr.to_v6(), target_mac_addr,
                                0, true);
            }
        }

        return;
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

    void SendNDAdvert(short ifindex, Ip6Address src_ip, Ip6Address dest_ip,
                  Ip6Address target_ip, MacAddress target_mac,
                  uint32_t type, bool csum) {
        int len = 512;
        uint8_t *buf = new uint8_t[len];
        memset(buf, 0, len);

        struct ether_header *eth = (struct ether_header *)buf;
        eth->ether_dhost[5] = 1;
        eth->ether_shost[5] = 2;
        eth->ether_type = htons(0x800);

        agent_hdr *agent = (agent_hdr *)(eth + 1);
        agent->hdr_ifindex = htons(ifindex);
        agent->hdr_vrf = htons(0);
        agent->hdr_cmd = htons(AgentHdr::TRAP_NEXTHOP);

        eth = (struct ether_header *) (agent + 1);
        memcpy(eth->ether_dhost, dest_mac, MAC_LEN);
        memcpy(eth->ether_shost, src_mac, MAC_LEN);
        eth->ether_type = htons(ETHERTYPE_IPV6);

        ip6_hdr *ip = (ip6_hdr *) (eth + 1);
        ip->ip6_flow = htonl(0x60000000); // version 6, TC and Flow set to 0
        ip->ip6_plen = htons(64);
        ip->ip6_nxt = IPPROTO_ICMPV6;
        ip->ip6_hlim = 16;
        memcpy(ip->ip6_src.s6_addr, src_ip.to_bytes().data(), 16);
        memcpy(ip->ip6_dst.s6_addr, dest_ip.to_bytes().data(), 16);

        nd_neighbor_advert *icmp = (nd_neighbor_advert *)(ip + 1);
        icmp->nd_na_type = ND_NEIGHBOR_ADVERT;
        icmp->nd_na_code = 0;
        icmp->nd_na_cksum = 0;

        uint32_t plen = 0;
        uint32_t pseudo = 0;
        if (csum) {
            plen = htonl((uint32_t)64);
            // plen = sizeof(nd_neighbor_advert) + sizeof(nd_opt_hdr) + ETHER_ADDR_LEN;
            uint32_t next = htonl((uint32_t)IPPROTO_ICMPV6);
            pseudo = 0;
            pseudo = Sum((uint16_t *)src_ip.to_bytes().data(), 16, 0);
            pseudo = Sum((uint16_t *)dest_ip.to_bytes().data(), 16, pseudo);
            pseudo = Sum((uint16_t *)&plen, 4, pseudo);
            pseudo = Sum((uint16_t *)&next, 4, pseudo);
        }

        icmp->nd_na_flags_reserved = 0;
        icmp->nd_na_flags_reserved |= ND_NA_FLAG_SOLICITED;
        memcpy(icmp->nd_na_target.s6_addr, target_ip.to_bytes().data(), 16);

        uint16_t offset = sizeof(nd_neighbor_advert);
        nd_opt_hdr *src_linklayer_addr = (nd_opt_hdr *)(icmp + 1);
        src_linklayer_addr->nd_opt_type = ND_OPT_TARGET_LINKADDR;
        src_linklayer_addr->nd_opt_len = 6; 
        //XXX instead of ETHER_ADDR_LEN, actual buffer size should be given
        //to preven buffer overrun.
        target_mac.ToArray((uint8_t*)icmp + offset + sizeof(nd_opt_hdr), ETHER_ADDR_LEN);
        offset += sizeof(nd_opt_hdr) + ETHER_ADDR_LEN;

        if (csum) {
            icmp->nd_na_cksum = Csum((uint16_t *)icmp, 64, pseudo);
        }

        len = 64; // ideally sizeof(nd_neighbor_advert) + sizeof(nd_opt_hdr) + ETHER_ADDR_LEN;

        len += sizeof(struct ip6_hdr) + sizeof(struct ether_header) +
            Agent::GetInstance()->pkt()->pkt_handler()->EncapHeaderLen();

        TestPkt0Interface *tap = (TestPkt0Interface *)
                (Agent::GetInstance()->pkt()->control_interface());
        tap->TxPacket(buf, len);
    }

    unsigned int intf_count_;
    unsigned int icmpv6_rx_count_;
    BgpPeer *bgp_peer_[kControlNodes];
    Agent *agent_;
};

void StartControlNodeMock() {

    Agent *agent = Agent::GetInstance();

    for (uint32_t i = 0; i < kControlNodes; i++) {
        cn_thread[i] = new ServerThread(&cn_evm[i]);
        cn_bgp_peer[i] = new test::ControlNodeMock(&cn_evm[i], "127.0.0.1");

        agent->set_controller_ifmap_xmpp_server("127.0.0.1", i);
        agent->set_controller_ifmap_xmpp_port(cn_bgp_peer[i]->GetServerPort(), i);
        agent->set_dns_server("", i);
        agent->set_dns_server_port(cn_bgp_peer[i]->GetServerPort(), i);

        cn_thread[i]->Start();
    }

    return;
}

void StopControlNodeMock() {

    for (uint32_t i = 0; i < kControlNodes; i++) {

        cn_bgp_peer[i]->Shutdown();
        client->WaitForIdle();
        delete cn_bgp_peer[i];

        cn_evm[i].Shutdown();
        cn_thread[i]->Join();
        delete cn_thread[i];
    }

    client->WaitForIdle();

    return;
}

TEST_F(Ipv6UnderlayTest, ipv6_1) {
    boost::system::error_code ec;

    // Lookup vhost address
    Ip6Address addr = Ip6Address::from_string("2001::03", ec);
    InetUnicastRouteEntry* rt = RouteGetV6("default-domain:default-project:ip-fabric:__default__", addr, 128);
    EXPECT_TRUE(rt != NULL);
    EXPECT_TRUE(rt->GetActiveNextHop()->GetType() == NextHop::RECEIVE);

    // Lookup subnet address
    addr = Ip6Address::from_string("2001::00", ec);
    rt = RouteGetV6("default-domain:default-project:ip-fabric:__default__", addr, 64);
    EXPECT_TRUE(rt != NULL);
    EXPECT_TRUE(rt->GetActiveNextHop()->GetType() == NextHop::RESOLVE);

    // Lookup ipv6 default gateway address
    sleep(1);
    client->WaitForIdle();

    addr = Ip6Address::from_string("2001::01", ec);
    rt = RouteGetV6("default-domain:default-project:ip-fabric:__default__", addr, 128);
    EXPECT_TRUE(rt != NULL);
    EXPECT_TRUE(rt->GetActiveNextHop()->GetType() == NextHop::NDP);
    const NextHop *nh = rt->GetActiveNextHop();
    const NdpNH *ndp_nh = dynamic_cast<const NdpNH *>(nh);

    EXPECT_TRUE(ndp_nh->GetMac() == target_gw_mac);
    client->WaitForIdle();

    // Lookup ipv6 default route
    addr = Ip6Address::from_string("::0", ec);
    rt = RouteGetV6("default-domain:default-project:ip-fabric:__default__", addr, 0);
    EXPECT_TRUE(rt != NULL);
}

TEST_F(Ipv6UnderlayTest, ipv6_2) {
    struct PortInfo input[] = {
        {"vnet1", 1, "10.10.10.1", "00:00:00:01:01:01", 1, 1, "2002::1"},
        {"vnet2", 2, "10.10.10.2", "00:00:00:02:02:02", 1, 2, "2002::2"},
    };

    CreateV6VmportEnv(input, 2, 0);
    client->WaitForIdle();

    IpAddress tunnel_dest_1 = IpAddress(Ip6Address::from_string(TARGET_RC_1_IPV6));
    IpAddress tunnel_dest_2 = IpAddress(Ip6Address::from_string(TARGET_RC_2_IPV6));
    IpAddress tunnel_dest_3 = IpAddress(Ip6Address::from_string(TARGET_RC_3_IPV6));
    IpAddress prefix_addr_1 = IpAddress(Ip6Address::from_string("2002::03"));
    IpAddress prefix_addr_2 = IpAddress(Ip6Address::from_string("2002::04"));
    IpAddress prefix_addr_3 = IpAddress(Ip6Address::from_string("2002::05"));
    uint32_t prefix_len = 128;

    VnListType dest_vn_list;
    dest_vn_list.insert("vn1");
    SecurityGroupList sg_list;
    TagList tag_list;
    PathPreference path_preference;
    bool ecmp_suppressed = false;
    EcmpLoadBalance ecmp_load_balance;
    bool etree_leaf = false;

    ControllerVmRoute *vm_route = ControllerVmRoute::MakeControllerVmRoute(
                                            agent_, bgp_peer(1), "vrf1", tunnel_dest_1,
                                            TunnelType::NativeMplsType(),
                                            100, MacAddress(), dest_vn_list,
                                            sg_list, tag_list, path_preference,
                                            ecmp_suppressed, ecmp_load_balance, etree_leaf);

    InetUnicastAgentRouteTable *rt_table = agent_->vrf_table()->GetInet4UnicastRouteTable("vrf1");
    rt_table->AddRemoteVmRouteReq(bgp_peer(1), "vrf1", prefix_addr_1, prefix_len, vm_route);
    client->WaitForIdle();

    vm_route = ControllerVmRoute::MakeControllerVmRoute(
                                            agent_, bgp_peer(1), "vrf1", tunnel_dest_2,
                                            TunnelType::NativeMplsType(),
                                            100, MacAddress(), dest_vn_list,
                                            sg_list, tag_list, path_preference,
                                            ecmp_suppressed, ecmp_load_balance, etree_leaf);

    rt_table->AddRemoteVmRouteReq(bgp_peer(1), "vrf1", prefix_addr_2, prefix_len, vm_route);
    client->WaitForIdle();

    vm_route = ControllerVmRoute::MakeControllerVmRoute(
                                            agent_, bgp_peer(1), "vrf1", tunnel_dest_3,
                                            TunnelType::UDPType(),
                                            100, MacAddress(), dest_vn_list,
                                            sg_list, tag_list, path_preference,
                                            ecmp_suppressed, ecmp_load_balance, etree_leaf);

    rt_table->AddRemoteVmRouteReq(bgp_peer(1), "vrf1", prefix_addr_3, prefix_len, vm_route);
    client->WaitForIdle();

    sleep(1);
    client->WaitForIdle();

    InetUnicastRouteEntry* rt = RouteGetV6("vrf1", prefix_addr_1.to_v6(), prefix_len);
    EXPECT_TRUE(rt != NULL);
    EXPECT_TRUE(rt->GetActiveNextHop()->GetType() == NextHop::TUNNEL);
    const NextHop *nh = rt->GetActiveNextHop();
    const TunnelNH *tunnel_nh = dynamic_cast<const TunnelNH *>(nh);
    EXPECT_TRUE(*tunnel_nh->GetDmac() == target_rc_1_mac);
    client->WaitForIdle();

    rt = RouteGetV6("vrf1", prefix_addr_2.to_v6(), prefix_len);
    EXPECT_TRUE(rt != NULL);
    EXPECT_TRUE(rt->GetActiveNextHop()->GetType() == NextHop::TUNNEL);
    nh = rt->GetActiveNextHop();
    tunnel_nh = dynamic_cast<const TunnelNH *>(nh);
    EXPECT_TRUE(*tunnel_nh->GetDmac() == target_rc_2_mac);
    client->WaitForIdle();

    rt = RouteGetV6("vrf1", prefix_addr_3.to_v6(), prefix_len);
    EXPECT_TRUE(rt != NULL);
    EXPECT_TRUE(rt->GetActiveNextHop()->GetType() == NextHop::TUNNEL);
    nh = rt->GetActiveNextHop();
    tunnel_nh = dynamic_cast<const TunnelNH *>(nh);
    EXPECT_TRUE(*tunnel_nh->GetDmac() == target_gw_mac);
    client->WaitForIdle();

    VrfKey vrf_key("vrf1");
    VrfEntry *vrf = static_cast<VrfEntry *>(agent_->vrf_table()->
                                FindActiveEntry(&vrf_key));
    rt_table = vrf->GetInet6UnicastRouteTable();
    rt_table->DeleteReq(bgp_peer(1), "vrf1", prefix_addr_1, prefix_len,
                                new ControllerVmRoute(bgp_peer(1)));
    client->WaitForIdle();

    rt = RouteGetV6("vrf1", prefix_addr_1.to_v6(), prefix_len);
    EXPECT_TRUE(rt == NULL);
    client->WaitForIdle();

    rt_table->DeleteReq(bgp_peer(1), "vrf1", prefix_addr_2, prefix_len,
                                new ControllerVmRoute(bgp_peer(1)));
    client->WaitForIdle();

    rt = RouteGetV6("vrf1", prefix_addr_2.to_v6(), prefix_len);
    EXPECT_TRUE(rt == NULL);
    client->WaitForIdle();

    rt_table->DeleteReq(bgp_peer(1), "vrf1", prefix_addr_3, prefix_len,
                                new ControllerVmRoute(bgp_peer(1)));
    client->WaitForIdle();

    rt = RouteGetV6("vrf1", prefix_addr_3.to_v6(), prefix_len);
    EXPECT_TRUE(rt == NULL);
    client->WaitForIdle();
    DeleteVmportEnv(input, 2, 1, 0, NULL, NULL, true, true);
    client->WaitForIdle();
}

TEST_F(Ipv6UnderlayTest, ipv6_3) {
    struct PortInfo input[] = {
        {"vnet1", 1, "10.10.10.1", "00:00:00:01:01:01", 1, 1, "2002::1"},
        {"vnet2", 2, "10.10.10.2", "00:00:00:02:02:02", 1, 2, "2002::2"},
    };

    CreateVmportEnv(input, 2, 0);
    client->WaitForIdle();

    IpAddress tunnel_dest_1 = IpAddress(Ip6Address::from_string(TARGET_RC_1_IPV6));
    IpAddress prefix_addr = IpAddress(Ip4Address::from_string("10.10.10.10"));
    uint32_t prefix_len = 32;

    VnListType dest_vn_list;
    dest_vn_list.insert("vn1");
    SecurityGroupList sg_list;
    TagList tag_list;
    PathPreference path_preference;
    bool ecmp_suppressed = false;
    EcmpLoadBalance ecmp_load_balance;
    bool etree_leaf = false;

    ControllerVmRoute *vm_route = ControllerVmRoute::MakeControllerVmRoute(
                                            agent_, bgp_peer(1), "vrf1", tunnel_dest_1,
                                            TunnelType::NativeMplsType(),
                                            100, MacAddress(), dest_vn_list,
                                            sg_list, tag_list, path_preference,
                                            ecmp_suppressed, ecmp_load_balance, etree_leaf);

    InetUnicastAgentRouteTable *rt_table = agent_->vrf_table()->GetInet4UnicastRouteTable("vrf1");
    rt_table->AddRemoteVmRouteReq(bgp_peer(1), "vrf1", prefix_addr, prefix_len, vm_route);
    sleep(1);
    client->WaitForIdle();

    InetUnicastRouteEntry* rt = RouteGet("vrf1", prefix_addr.to_v4(), prefix_len);
    EXPECT_TRUE(rt != NULL);
    EXPECT_TRUE(rt->GetActiveNextHop()->GetType() == NextHop::TUNNEL);
    const NextHop *nh = rt->GetActiveNextHop();
    const TunnelNH *tunnel_nh = dynamic_cast<const TunnelNH *>(nh);
    EXPECT_TRUE(*tunnel_nh->GetDmac() == target_rc_1_mac);
    client->WaitForIdle();

    VrfKey vrf_key("vrf1");
    VrfEntry *vrf = static_cast<VrfEntry *>(agent_->vrf_table()->
                                FindActiveEntry(&vrf_key));
    rt_table = vrf->GetInet4UnicastRouteTable();
    rt_table->DeleteReq(bgp_peer(1), "vrf1", prefix_addr, prefix_len,
                                new ControllerVmRoute(bgp_peer(1)));
    client->WaitForIdle();

    rt = RouteGet("vrf1", prefix_addr.to_v4(), prefix_len);
    EXPECT_TRUE(rt == NULL);

    DeleteVmportEnv(input, 2, 1, 0);
    client->WaitForIdle();
}

TEST_F(Ipv6UnderlayTest, ipv4_1) {
    struct PortInfo input[] = {
        {"vnet1", 1, "10.10.10.1", "00:00:00:01:01:01", 1, 1, "2002::1"},
        {"vnet2", 2, "10.10.10.2", "00:00:00:02:02:02", 1, 2, "2002::2"},
    };

    CreateVmportEnv(input, 2, 0);
    client->WaitForIdle();

    IpAddress tunnel_dest_1 = IpAddress(Ip4Address::from_string("10.1.1.3"));
    IpAddress prefix_addr = IpAddress(Ip4Address::from_string("10.10.10.3"));
    uint32_t prefix_len = 32;

    VnListType dest_vn_list;
    dest_vn_list.insert("vn1");
    SecurityGroupList sg_list;
    TagList tag_list;
    PathPreference path_preference;
    bool ecmp_suppressed = false;
    EcmpLoadBalance ecmp_load_balance;
    bool etree_leaf = false;

    ControllerVmRoute *vm_route = ControllerVmRoute::MakeControllerVmRoute(
                                            agent_, bgp_peer(1), "vrf1", tunnel_dest_1,
                                            TunnelType::NativeMplsType(),
                                            100, MacAddress(), dest_vn_list,
                                            sg_list, tag_list, path_preference,
                                            ecmp_suppressed, ecmp_load_balance, etree_leaf);

    InetUnicastAgentRouteTable *rt_table = agent_->vrf_table()->GetInet4UnicastRouteTable("vrf1");
    rt_table->AddRemoteVmRouteReq(bgp_peer(1), "vrf1", prefix_addr, prefix_len, vm_route);
    client->WaitForIdle();

    InetUnicastRouteEntry* rt = RouteGet("vrf1", prefix_addr.to_v4(), 32);
    EXPECT_TRUE(rt != NULL);
    EXPECT_TRUE(rt->GetActiveNextHop()->GetType() == NextHop::TUNNEL);
    client->WaitForIdle();

    VrfKey vrf_key("vrf1");
    VrfEntry *vrf = static_cast<VrfEntry *>(agent_->vrf_table()->
                                FindActiveEntry(&vrf_key));
    rt_table = vrf->GetInet4UnicastRouteTable();
    rt_table->DeleteReq(bgp_peer(1), "vrf1", prefix_addr, prefix_len,
                                new ControllerVmRoute(bgp_peer(1)));
    client->WaitForIdle();

    rt = RouteGet("vrf1", prefix_addr.to_v4(), 32);
    EXPECT_TRUE(rt == NULL);

    DeleteVmportEnv(input, 2, 1, 0);
    client->WaitForIdle();
}

int main(int argc, char **argv) {
    GETUSERARGS();

    client = TestInit(DEFAULT_VNSW_IPV6_UNDERLAY_CONFIG_FILE, ksync_init, false, true, false);
    client->WaitForIdle();
    usleep(100000);

    StartControlNodeMock();
    client->WaitForIdle();

    Agent *agent = Agent::GetInstance();
    RouterIdDepInit(agent);

    int ret = RUN_ALL_TESTS();
    usleep(10000);

    StopControlNodeMock();
    client->WaitForIdle();

    TestShutdown();
    delete client;

    return ret;
}
