/*
 * Copyright (c) 2013 Juniper Networks, Inc. All rights reserved.
 */

#ifndef vnsw_agent_ndp_entry_hpp
#define vnsw_agent_ndp_entry_hpp


#include "base/timer.h"
#include <boost/statechart/state_machine.hpp>
#include <netinet/icmp6.h>
#include "services/icmpv6_handler.h"

namespace sc = boost::statechart;
class NdpEntry;

namespace fsm {
struct NoState;
}

struct NdpKey {
    NdpKey(Ip6Address addr, const VrfEntry *ventry) : ip(addr), vrf(ventry) {};
    NdpKey(const NdpKey &key) : ip(key.ip), vrf(key.vrf) {};
    bool operator <(const NdpKey &rhs) const {
        if (vrf != rhs.vrf)
            return vrf < rhs.vrf;
        return (ip  < rhs.ip);
    }

    Ip6Address ip;
    const VrfEntry *vrf;
};

typedef boost::function<bool(NdpEntry*)> EvValidate;

// Represents each NDP entry maintained by the Icmpv6 module
class NdpEntry : public sc::state_machine<NdpEntry, fsm::NoState> {
public:
    NdpEntry(boost::asio::io_service &io, Icmpv6Handler *handler,
             NdpKey &key, const VrfEntry *vrf, const Interface *itf);
    virtual ~NdpEntry();

    typedef boost::function<void(void)> EventCB;

    static const int kMaxRetries;
    static const int kMaxUnicastRetries;

    enum State {
        NOSTATE     = 0,
        INCOMPLETE  = 1,
        REACHABLE   = 2,
        STALE       = 3,
        DELAY       = 4,
        PROBE       = 5
    };

    const NdpKey &key() const { return key_; }
    const Interface *get_interface() const { return interface_.get(); }

    void StartRetransmitTimer();
    void StartReachableTimer();
    void StartDelayTimer();
    void DeleteAllTimers();

    const std::string &StateName() const;
    const std::string &LastStateName() const;

    struct EventContainer {
        boost::intrusive_ptr<const sc::event_base> event;
        EvValidate validate;
    };

    int retry_count() const { return retry_count_; }
    void retry_count_inc() { retry_count_++; }
    void retry_count_clear() { retry_count_ = 0; }
    void retry_count_set(int rc) { retry_count_ = rc; }

    int retransmit_time() const { return retransmit_time_; }
    void set_retransmit_time(int t) { retransmit_time_ = t; }
    int reachable_time() const { return reachable_time_; }
    void set_reachable_time(int t) { reachable_time_ = t; }

    void set_state(State state);
    State get_state() const { return state_; }
    const std::string last_state_change_at() const;
    const uint64_t last_state_change_usecs_at() const;
    void set_last_event(const std::string &event);
    const std::string &last_event() const { return last_event_; }
    MacAddress mac() const { return mac_; }
    void set_mac(MacAddress mac) { mac_ = mac; }

    void set_last_notification_in(int code, int subcode,
        const std::string &reason);
    void set_last_notification_out(int code, int subcode,
        const std::string &reason);
    void reset_last_info();
    void LogEvent(std::string event_name, std::string msg,
                  SandeshLevel::type log_level = SandeshLevel::SYS_DEBUG);
    bool RetransmitTimerExpired();
    bool ReachableTimerExpired();
    bool DelayTimerExpired();
    bool EnqueuePktOut();
    bool EnqueueTestStateChange(State state, int retry_count);
    bool EnqueueRetransmitTimerExpired();
    bool EnqueueReachableTimerExpired();
    bool EnqueueDelayTimerExpired();
    bool EnqueueNaIn(nd_neighbor_advert *na, MacAddress mac);
    bool EnqueueSolNaIn(nd_neighbor_advert *na, MacAddress mac);
    bool EnqueueUnsolNaIn(nd_neighbor_advert *na, MacAddress mac);
    bool EnqueueNsIn(nd_neighbor_solicit *ns, MacAddress mac);

    template <typename Ev> bool Enqueue(const Ev &event);
    bool DequeueEvent(EventContainer ec);
    void DequeueEventDone(bool done);
    void UpdateFlapCount();
    Timer* retransmit_timer() { return retransmit_timer_; };
    Timer* reachable_timer() { return reachable_timer_; };
    Timer* delay_timer() { return delay_timer_; };

    bool DeleteNdpRoute();
    bool IsResolved();
    void Resync(bool policy, const VnListType &vnlist,
                const SecurityGroupList &sg,
                const TagList &tag);
    void HandleNsRequest(nd_neighbor_solicit *ns, MacAddress mac);
    void SendNeighborSolicit(bool send_unicast=false);
    void SendNeighborAdvert(bool solicited);
private:
    void AddNdpRoute(bool resolved);
    bool IsDerived();

    WorkQueue<EventContainer> work_queue_;
    Timer *delay_timer_;
    Timer *retransmit_timer_;
    Timer *reachable_timer_;
    int retransmit_time_;
    int delay_time_;
    int reachable_time_;
    int retry_count_;
    bool deleted_;
    State state_;
    State last_state_;
    MacAddress mac_;
    std::string last_event_;
    uint64_t last_event_at_;
    uint64_t last_state_change_at_;
    std::pair<int, int> last_notification_in_;
    std::string last_notification_in_error_;
    uint64_t last_notification_in_at_;
    std::pair<int, int> last_notification_out_;
    std::string last_notification_out_error_;
    uint64_t last_notification_out_at_;
    boost::asio::io_service &io_;
    NdpKey key_;
    const VrfEntry *nh_vrf_;
    boost::intrusive_ptr<Icmpv6Handler> handler_;
    InterfaceConstRef interface_;
    DISALLOW_COPY_AND_ASSIGN(NdpEntry);
};

#endif // vnsw_agent_ndp_entry_hpp
