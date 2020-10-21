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

using namespace std;
using namespace boost::assign;
using namespace boost::posix_time;

#define GRAT_IP "4.5.6.7"
#define DIFF_NET_IP "3.2.6.9"
#define MAX_WAIT_COUNT 50
short req_ifindex = 1, reply_ifindex = 1;
MacAddress src_mac(0x00, 0x01, 0x02, 0x03, 0x04, 0x05);
MacAddress dest_mac(0x00, 0x01, 0x02, 0x03, 0x04, 0x05);
MacAddress mac(0x00, 0x05, 0x07, 0x09, 0x0a, 0x0b);

class NdpEntryTest : public ::testing::Test {
protected:
    NdpEntryTest() :
        trigger_(boost::bind(&NdpEntryTest::AddVhostRcvRoute, this),
                         TaskScheduler::GetInstance()->GetTaskId("db::DBTable"),
                         0) {}

    ~NdpEntryTest() {
        const VrfEntry *vrf = Agent::GetInstance()->vrf_table()->FindVrfFromName(
            Agent::GetInstance()->fabric_vrf_name());
        NdpKey key(ip1, vrf);
        Agent::GetInstance()->fabric_inet4_unicast_table()->DeleteReq(
                                        Agent::GetInstance()->local_peer(),
                                        Agent::GetInstance()->fabric_vrf_name(),
                                        ip1, 128, NULL);
        client->WaitForIdle();
        EXPECT_TRUE(Agent::GetInstance()->icmpv6_proto()->
                    FindUnsolNaEntry(key) == NULL);
    }

    void TriggerAddVhostRcvRoute(Ip6Address &ip) {
        vhost_rcv_route_ = ip;
        trigger_.Set();
    }

    bool AddVhostRcvRoute() {
        VmInterfaceKey vmi_key(AgentKey::ADD_DEL_CHANGE,
                               boost::uuids::nil_uuid(), "vhost0");
        Agent::GetInstance()->fabric_inet4_unicast_table()->
            AddVHostRecvRoute(Agent::GetInstance()->local_peer(),
                              Agent::GetInstance()->fabric_vrf_name(),
                              vmi_key, vhost_rcv_route_, 128, "", false,
                              true);
        return true;
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

    void SendNdpMessage(Icmpv6Proto::Icmpv6MsgType type, Ip6Address addr) {
        PhysicalInterfaceKey key(Agent::GetInstance()->fabric_interface_name());
        Interface *eth = static_cast<Interface *>
            (Agent::GetInstance()->interface_table()->FindActiveEntry(&key));
        Icmpv6Proto::Icmpv6Ipc *ipc =
                new Icmpv6Proto::Icmpv6Ipc(type, addr,
                    Agent::GetInstance()->vrf_table()->FindVrfFromName(
                        Agent::GetInstance()->fabric_vrf_name()), eth);
        Agent::GetInstance()->pkt()->pkt_handler()->SendMessage(
                                                    PktHandler::ICMPV6, ipc);
    }

    bool FindNdpRoute(Ip6Address ip, const string &vrf_name) {
        Agent *agent = Agent::GetInstance();
        InetUnicastRouteKey rt_key(agent->local_peer(), vrf_name, ip, 128);
        VrfEntry *vrf = Agent::GetInstance()->vrf_table()->FindVrfFromName(vrf_name);
        int count = 0;
        for (int count = 0; count < 100; count++) {
            if (!vrf || !(vrf->GetInet6UnicastRouteTable()))
                usleep(10);
            else break;
        }
        if (count == 100)
            return false;
        InetUnicastRouteEntry *rt = NULL;
        for (count = 0; count < 100; count++) {
            rt = static_cast<InetUnicastRouteEntry *>
                (static_cast<InetUnicastAgentRouteTable *>(vrf->
                GetInet6UnicastRouteTable())->FindActiveEntry(&rt_key));
            if (!rt) {
                usleep(10);
            } else break;
        }
        if (rt)
            return true;
        else
            return false;
    }

    bool ValidateNdpEntry(Ip6Address ip, MacAddress mac) {
        NdpKey key(ip, Agent::GetInstance()->fabric_policy_vrf());
        NdpEntry *entry = Agent::GetInstance()->icmpv6_proto()->FindNdpEntry(key);
        if (!entry)
            return false;
        for (int count = 0; count < 100; count++) {
            if (entry->mac() == mac)
                return true;
            client->WaitForIdle();
        }
        return false;
    }

    bool FindNdpNHEntry(Ip6Address addr, const string &vrf_name, bool validate = false) {
        Ip6Address ip(addr);
        NdpNHKey key(vrf_name, ip, false);
        NdpNH *ndp_nh = NULL;
        for (int count = 0; count < 100; count++) {
            ndp_nh = static_cast<NdpNH *>(Agent::GetInstance()->
                                      nexthop_table()-> FindActiveEntry(&key));
            if (ndp_nh)
                break;
            usleep(1);
        }
        if (ndp_nh) {
            if (validate)
                return ndp_nh->IsValid();
            return true;
        } else
            return false;
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

    void SendNS(short ifindex, short vrf, uint8_t *sip, uint8_t *tip) {
        return SendND(ifindex, vrf, sip, tip, true);
    }
    void SendNA(short ifindex, short vrf, uint8_t *sip, uint8_t *tip,
                bool solicit = false) {
        return SendND(ifindex, vrf, sip, tip, false, solicit);
    }

    virtual void SetUp() {
    }

    virtual void TearDown() {
    }

    void RunToState(NdpEntry::State state) {
        client->WaitForIdle();
        for (int count = 0; count < 100 && sm_->get_state() != state; count++) {
            client->WaitForIdle();
        }
        VerifyState(state);
    }

    void GetToState(NdpEntry::State state, int retry_count =
                    NdpEntry::kMaxRetries) {
        sm_->EnqueueTestStateChange(state, retry_count);
        return;
    }

    void VerifyState(NdpEntry::State state) {
        client->WaitForIdle();

        TASK_UTIL_EXPECT_EQ(state, sm_->get_state());
    }

    void EvSolNaIn() {
        nd_neighbor_advert na;
        na.nd_na_flags_reserved = ND_NA_FLAG_SOLICITED;
        sm_->EnqueueSolNaIn(&na, MacAddress("01:00:00:00:00:00"));
    }
    void EvSolNaOrIn() {
        nd_neighbor_advert na;
        na.nd_na_flags_reserved = ND_NA_FLAG_OVERRIDE | ND_NA_FLAG_SOLICITED;
        sm_->EnqueueSolNaIn(&na, MacAddress("01:00:00:00:00:00"));
    }
    void EvNsIn() {
        sm_->EnqueueNsIn(NULL, MacAddress("01:00:00:00:00:00"));
    }
    void EvPktOut() {
        sm_->EnqueuePktOut();
    }
    void EvRetransmitTimerExpired() {
        sm_->retransmit_timer()->Fire();
    }
    void EvReachableTimerExpired() {
        sm_->reachable_timer()->Fire();
    }
    void EvDelayTimerExpired() {
        sm_->delay_timer()->Fire();
    }
    void EvUnsolNaIn() {
        nd_neighbor_advert na;
        na.nd_na_flags_reserved = ND_NA_FLAG_OVERRIDE | ND_NA_FLAG_SOLICITED;
        sm_->EnqueueUnsolNaIn(&na, MacAddress("01:00:00:00:00:00"));
    }

    NdpEntry *sm_;
    Ip6Address ip1;
    EventManager evm_;
    Ip6Address vhost_rcv_route_;
    TaskTrigger trigger_;
};

typedef boost::function<void(void)> EvGen;
struct EvGenComp {
    bool operator()(const EvGen &lhs, const EvGen &rhs) const {
        return &lhs < &rhs;
    }
};

TEST_F(NdpEntryTest, Matrix) {
    boost::system::error_code ec;
    Ip6Address src1_ip = Ip6Address::from_string("fd15::5", ec);
    Ip6Address dest1_ip = Ip6Address::from_string("fd15::1", ec);

    SendNS(req_ifindex, 0, src1_ip.to_bytes().data(), dest1_ip.to_bytes().data());
    client->WaitForIdle();
    EXPECT_TRUE(FindNdpNHEntry(src1_ip, Agent::GetInstance()->fabric_policy_vrf_name()));
    EXPECT_TRUE(FindNdpRoute(src1_ip, Agent::GetInstance()->fabric_policy_vrf_name()));
    EXPECT_EQ(1U, Agent::GetInstance()->icmpv6_proto()->GetNdpCacheSize());

    NdpKey key(src1_ip, Agent::GetInstance()->fabric_policy_vrf());
    NdpEntry *entry = Agent::GetInstance()->icmpv6_proto()->FindNdpEntry(key);
    sm_ = entry;

    typedef map<EvGen, NdpEntry::State, EvGenComp> Transitions;

#define TRANSITION(F, E) \
    ((EvGen) boost::bind(&NdpEntryTest_Matrix_Test::F, this), E)

    Transitions nostate = map_list_of
            TRANSITION(EvNsIn, NdpEntry::STALE)
            TRANSITION(EvPktOut, NdpEntry::INCOMPLETE);

    Transitions incomplete = map_list_of
            TRANSITION(EvNsIn, NdpEntry::STALE)
            TRANSITION(EvSolNaIn, NdpEntry::REACHABLE)
            TRANSITION(EvUnsolNaIn, NdpEntry::STALE)
            TRANSITION(EvRetransmitTimerExpired, NdpEntry::INCOMPLETE);

    Transitions reachable = map_list_of
            TRANSITION(EvNsIn, NdpEntry::STALE)
            TRANSITION(EvSolNaIn, NdpEntry::STALE)
            TRANSITION(EvUnsolNaIn, NdpEntry::STALE)
            TRANSITION(EvReachableTimerExpired, NdpEntry::STALE);

    Transitions stale = map_list_of
            TRANSITION(EvNsIn, NdpEntry::STALE)
            TRANSITION(EvSolNaOrIn, NdpEntry::REACHABLE)
            TRANSITION(EvUnsolNaIn, NdpEntry::STALE)
            TRANSITION(EvPktOut, NdpEntry::DELAY);

    Transitions delay = map_list_of
            TRANSITION(EvNsIn, NdpEntry::STALE)
            TRANSITION(EvSolNaOrIn, NdpEntry::REACHABLE)
            TRANSITION(EvUnsolNaIn, NdpEntry::STALE)
            TRANSITION(EvDelayTimerExpired, NdpEntry::PROBE);

    Transitions probe = map_list_of
            TRANSITION(EvNsIn, NdpEntry::STALE)
            TRANSITION(EvSolNaOrIn, NdpEntry::REACHABLE)
            TRANSITION(EvUnsolNaIn, NdpEntry::STALE)
            TRANSITION(EvRetransmitTimerExpired, NdpEntry::PROBE);

    Transitions matrix[] =
        { nostate, incomplete, reachable, stale, delay, probe};

    for (int k = NdpEntry::NOSTATE; k <= NdpEntry::PROBE; k++) {
        NdpEntry::State i = static_cast<NdpEntry::State> (k);
        int count = 0;
        for (Transitions::iterator j = matrix[i].begin(); j != matrix[i].end();
                            j++) {
            GetToState(i);
            j->first();
            RunToState(j->second);
        }
    }
}

//
// Send NS, it should result in creating NDP entry
// This entry should get deleted after retransmit timer fires k times
//
TEST_F(NdpEntryTest, Basic) {
    boost::system::error_code ec;
    Ip6Address src1_ip = Ip6Address::from_string("fd15::5", ec);
    Ip6Address dest1_ip = Ip6Address::from_string("fd15::1", ec);

    SendNS(req_ifindex, 0, src1_ip.to_bytes().data(), dest1_ip.to_bytes().data());
    client->WaitForIdle();
    EXPECT_TRUE(FindNdpNHEntry(src1_ip, Agent::GetInstance()->fabric_policy_vrf_name()));
    EXPECT_TRUE(FindNdpRoute(src1_ip, Agent::GetInstance()->fabric_policy_vrf_name()));
    EXPECT_EQ(1U, Agent::GetInstance()->icmpv6_proto()->GetNdpCacheSize());

    NdpKey key(src1_ip, Agent::GetInstance()->fabric_policy_vrf());
    NdpEntry *entry = Agent::GetInstance()->icmpv6_proto()->FindNdpEntry(key);
    entry->EnqueueTestStateChange(NdpEntry::PROBE, NdpEntry::kMaxRetries);
    entry->StartRetransmitTimer();
    usleep(1000);
    entry->retry_count_set(NdpEntry::kMaxRetries);
    entry->retransmit_timer()->Fire();
    client->WaitForIdle();
    usleep(1000);
    EXPECT_FALSE(FindNdpNHEntry(src1_ip, Agent::GetInstance()->fabric_policy_vrf_name()));
    EXPECT_FALSE(FindNdpRoute(src1_ip, Agent::GetInstance()->fabric_policy_vrf_name()));
    EXPECT_EQ(0, Agent::GetInstance()->icmpv6_proto()->GetNdpCacheSize());
}

// Check that NA for non-existing entry is ignored.
TEST_F(NdpEntryTest, NdpNonExistNaTest) {
    boost::system::error_code ec;
    Ip6Address src1_ip = Ip6Address::from_string("fd15::6", ec);
    Ip6Address dest1_ip = Ip6Address::from_string("fd15::2", ec);

    SendNA(req_ifindex, 0, src1_ip.to_bytes().data(),
           dest1_ip.to_bytes().data());
    client->WaitForIdle();
    EXPECT_FALSE(FindNdpNHEntry(src1_ip,
                                Agent::GetInstance()->fabric_policy_vrf_name()));
    EXPECT_FALSE(FindNdpRoute(src1_ip,
                              Agent::GetInstance()->fabric_policy_vrf_name()));
}

#if 0
// Check that an Unsol NA to existing entry is processed.
TEST_F(NdpEntryTest, NdpUnsolNaTest) {
    boost::system::error_code ec;
    Ip6Address src1_ip = Ip6Address::from_string("fd15::7", ec);
    Ip6Address dest1_ip = Ip6Address::from_string("fd15::3", ec);

    GetToState(NdpEntry::NOSTATE);
    SendNS(req_ifindex, 0, src1_ip.to_bytes().data(), dest1_ip.to_bytes().data());
    client->WaitForIdle();
    EXPECT_TRUE(FindNdpNHEntry(src1_ip, Agent::GetInstance()->fabric_policy_vrf_name()));
    EXPECT_TRUE(FindNdpRoute(src1_ip, Agent::GetInstance()->fabric_policy_vrf_name()));

    MacAddress zero_mac;
    EXPECT_TRUE(ValidateNdpEntry(src1_ip, zero_mac));
    SendNA(req_ifindex, 0, dest1_ip.to_bytes().data(),
           src1_ip.to_bytes().data());
    client->WaitForIdle();

    EXPECT_TRUE(ValidateNdpEntry(src1_ip, dest_mac));
}
#endif

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
