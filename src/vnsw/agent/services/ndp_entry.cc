/*
 * Copyright (c) 2013 Juniper Networks, Inc. All rights reserved.
 */

#include "base/os.h"
#include <boost/statechart/custom_reaction.hpp>
#include <boost/statechart/state.hpp>
#include <boost/statechart/state_machine.hpp>
#include <boost/statechart/transition.hpp>

#include "services/ndp_entry.h"
#include "services/services_types.h"
#include "services/icmpv6_proto.h"
//#include "services/services_sandesh.h"
#include "services/services_init.h"
#include "oper/route_common.h"

using std::ostream;
using std::ostringstream;
using std::string;

namespace mpl = boost::mpl;
namespace sc = boost::statechart;

const int NdpEntry::kMaxRetries = 6;

#define SM_LOG(level, _Msg)                                    \
    do {                                                       \
        ostringstream out;                                     \
        out << _Msg;                                           \
        if (LoggingDisabled()) break;                          \
    } while (false)

#define SM_LOG_NOTICE(_Msg)                                    \
    do {                                                       \
        ostringstream out;                                     \
        out << _Msg;                                           \
        if (LoggingDisabled()) break;                          \
    } while (false)

namespace fsm {

struct EvTestStateChange : sc::event<EvTestStateChange> {
    EvTestStateChange(NdpEntry::State state, int retry) :state_(state),
                        retry_(retry) {}
    static const char *Name() {
        return "EvTestStateChange";
    }
    bool validate(NdpEntry *state_machine) const {
        return true;
    }

    NdpEntry::State state_;
    int retry_;
};

struct EvPktOut : sc::event<EvPktOut> {
    EvPktOut() {
    }
    static const char *Name() {
        return "EvPktOut";
    }
    bool validate(NdpEntry *state_machine) const {
        return true;
    }
};

struct EvDelayTimerExpired : sc::event<EvDelayTimerExpired> {
    explicit EvDelayTimerExpired()  {
    }
    static const char *Name() {
        return "EvDelayTimerExpired";
    }
    bool validate(NdpEntry *state_machine) const {
        return true;
    }
};

struct EvRetransmitTimerExpired : sc::event<EvRetransmitTimerExpired> {
    explicit EvRetransmitTimerExpired()  {
    }
    static const char *Name() {
        return "EvRetransmitTimerExpired";
    }
    bool validate(NdpEntry *state_machine) const {
        return true;
    }
};

struct EvReachableTimerExpired : sc::event<EvReachableTimerExpired> {
    explicit EvReachableTimerExpired()  {
    }
    static const char *Name() {
        return "EvReachableTimerExpired";
    }
    bool validate(NdpEntry *state_machine) const {
        return true;
    }
};

struct EvNsIn : sc::event<EvNsIn> {
    explicit EvNsIn(nd_neighbor_solicit *ns, MacAddress mac) :
             mac_(mac), ns_(ns) {
    }
    static const char *Name() {
        return "EvNsIn";
    }
    bool validate(NdpEntry *state_machine) const {
        return true;
    }

    MacAddress mac_;
    nd_neighbor_solicit *ns_;
};

struct EvSolNaIn : sc::event<EvSolNaIn> {
    explicit EvSolNaIn(nd_neighbor_advert *na, MacAddress mac) :
        mac_(mac), na_(na) {
    }
    static const char *Name() {
        return "EvSolNaIn";
    }
    bool validate(NdpEntry *state_machine) const {
        return true;
    }

    MacAddress mac_;
    nd_neighbor_advert *na_;
};

struct EvUnsolNaIn : sc::event<EvUnsolNaIn> {
    explicit EvUnsolNaIn(nd_neighbor_advert *na, MacAddress mac) :
        mac_(mac), na_(na) {
    }
    static const char *Name() {
        return "EvUnsolNaIn";
    }
    bool validate(NdpEntry *state_machine) const {
        return true;
    }

    MacAddress mac_;
    nd_neighbor_advert *na_;
};

// States for the NDP state machine.
struct NoState;
struct Incomplete;
struct Reachable;
struct Stale;
struct Delay;
struct Probe;

//
//
struct NoState : sc::state<NoState, NdpEntry> {
    typedef mpl::list<
        sc::custom_reaction<EvNsIn>,
        sc::custom_reaction<EvPktOut>,
        sc::custom_reaction<EvTestStateChange>
    > reactions;

    explicit NoState(my_context ctx) : my_base(ctx) {
        NdpEntry *state_machine = &context<NdpEntry>();
        state_machine->set_state(NdpEntry::NOSTATE);
    }

    ~NoState() {
    }

    // copy the mac and move to stale
    sc::result react(const EvNsIn &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        state_machine->set_mac(event.mac_);
        return transit<Stale>();
    }

    // Send multicast NS probe and start retransmit timer
    sc::result react(const EvPktOut &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        // In UTs, ndp_entry may not be there
        if (state_machine->get_interface())
            state_machine->SendNeighborSolicit();
        state_machine->StartRetransmitTimer();
        return transit<Incomplete>();
    }

    sc::result react(const EvTestStateChange &event) {
        NdpEntry::State state = event.state_;
        NdpEntry *state_machine = &context<NdpEntry>();
        state_machine->set_state(state);
        state_machine->set_mac(MacAddress());
        switch (state) {
            case NdpEntry::NOSTATE: return transit<NoState>();
            case NdpEntry::INCOMPLETE: return transit<Incomplete>();
            case NdpEntry::REACHABLE: return transit<Reachable>();
            case NdpEntry::STALE: return transit<Stale>();
            case NdpEntry::DELAY: return transit<Delay>();
            case NdpEntry::PROBE: return transit<Probe>();
            default: return discard_event();
        }
    }
};

//
//
struct Incomplete : sc::state<Incomplete, NdpEntry> {
    typedef mpl::list<
        sc::custom_reaction<EvNsIn>,
        sc::custom_reaction<EvUnsolNaIn>,
        sc::custom_reaction<EvSolNaIn>,
        sc::custom_reaction<EvRetransmitTimerExpired>,
        sc::custom_reaction<EvTestStateChange>
    > reactions;

    explicit Incomplete(my_context ctx) : my_base(ctx) {
        NdpEntry *state_machine = &context<NdpEntry>();
        state_machine->retry_count_clear();
        state_machine->set_state(NdpEntry::INCOMPLETE);
    }

    ~Incomplete() {
    }

    // If different mac then move to stale
    sc::result react(const EvNsIn &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        if (state_machine->mac() != event.mac_) {
            state_machine->mac() = event.mac_;
            return transit<Stale>();
        }
        return discard_event();
    }

    // move to reachable
    sc::result react(const EvSolNaIn &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        if (state_machine->mac() != event.mac_) {
            state_machine->mac() = event.mac_;
        }
        return transit<Reachable>();
    }

    // move to stale
    sc::result react(const EvUnsolNaIn &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        state_machine->mac() = event.mac_;
        return transit<Stale>();
    }


    // If less than N retransmissions then retransmit and restart timer
    // Else discard entry and send icmp error
    sc::result react(const EvRetransmitTimerExpired &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        if (state_machine->retry_count() < NdpEntry::kMaxRetries) {
            // In UTs, ndp_entry may not be there
            if (state_machine->get_interface())
                state_machine->SendNeighborSolicit();
            state_machine->StartRetransmitTimer();
        } else {
            if (state_machine->DeleteNdpRoute())
                return discard_event();
            state_machine->retry_count_clear();
        }
        return discard_event();
    }

    sc::result react(const EvTestStateChange &event) {
        NdpEntry::State state = event.state_;
        NdpEntry *state_machine = &context<NdpEntry>();
        state_machine->set_state(state);
        state_machine->set_mac(MacAddress());
        switch (state) {
            case NdpEntry::NOSTATE: return transit<NoState>();
            case NdpEntry::INCOMPLETE: return transit<Incomplete>();
            case NdpEntry::REACHABLE: return transit<Reachable>();
            case NdpEntry::STALE: return transit<Stale>();
            case NdpEntry::DELAY: return transit<Delay>();
            case NdpEntry::PROBE: return transit<Probe>();
            default: return discard_event();
        }
    }
};

struct Reachable : sc::state<Reachable, NdpEntry> {
    typedef mpl::list<
        sc::custom_reaction<EvNsIn>,
        sc::custom_reaction<EvUnsolNaIn>,
        sc::custom_reaction<EvSolNaIn>,
        sc::custom_reaction<EvRetransmitTimerExpired>,
        sc::custom_reaction<EvReachableTimerExpired>,
        sc::custom_reaction<EvTestStateChange>
    > reactions;

    explicit Reachable(my_context ctx) : my_base(ctx) {
        NdpEntry *state_machine = &context<NdpEntry>();
        state_machine->set_state(NdpEntry::REACHABLE);
        state_machine->StartReachableTimer();
    }

    ~Reachable() {
    }

    // If different mac then move to stale
    sc::result react(const EvNsIn &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        if (state_machine->mac() != event.mac_) {
            state_machine->mac() = event.mac_;
            return transit<Stale>();
        }
        return discard_event();
    }


    // If different mac then move to stale else unchanged
    sc::result react(const EvUnsolNaIn &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        if (event.na_->nd_na_flags_reserved & ND_NA_FLAG_OVERRIDE) {
            if (state_machine->mac() != event.mac_) {
                state_machine->set_mac(event.mac_);
                return transit<Stale>();
            }
        }
        return discard_event();
    }


    // If non override and diff mac then move to stale
    // if override then update mac
    sc::result react(const EvSolNaIn &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        if (!(event.na_->nd_na_flags_reserved & ND_NA_FLAG_OVERRIDE)) {
            if (state_machine->mac() != event.mac_) {
                return transit<Stale>();
            }
        } else {
            if (state_machine->mac() != event.mac_) {
                state_machine->set_mac(event.mac_);
            }
        }
        return discard_event();
    }

    // If more than N retransmissions then move to stale
    sc::result react(const EvRetransmitTimerExpired &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        if (state_machine->retry_count() < NdpEntry::kMaxRetries) {
            if (state_machine->get_interface())
                state_machine->SendNeighborSolicit();
            state_machine->StartRetransmitTimer();
            return discard_event();
        } else {
            return transit<Stale>();
        }
    }

    // move to stale
    sc::result react(const EvReachableTimerExpired &event) {
        return transit<Stale>();
    }

    sc::result react(const EvTestStateChange &event) {
        NdpEntry::State state = event.state_;
        NdpEntry *state_machine = &context<NdpEntry>();
        state_machine->set_state(state);
        state_machine->set_mac(MacAddress());
        switch (state) {
            case NdpEntry::NOSTATE: return transit<NoState>();
            case NdpEntry::INCOMPLETE: return transit<Incomplete>();
            case NdpEntry::REACHABLE: return transit<Reachable>();
            case NdpEntry::STALE: return transit<Stale>();
            case NdpEntry::DELAY: return transit<Delay>();
            case NdpEntry::PROBE: return transit<Probe>();
            default: return discard_event();
        }
    }
};

//
//
struct Stale : sc::state<Stale, NdpEntry> {
    typedef mpl::list<
        sc::custom_reaction<EvNsIn>,
        sc::custom_reaction<EvUnsolNaIn>,
        sc::custom_reaction<EvSolNaIn>,
        sc::custom_reaction<EvPktOut>,
        sc::custom_reaction<EvTestStateChange>
    > reactions;

    // Send a KEEPALIVE and start the keepalive timer on the peer. Also start
    // the hold timer based on the negotiated hold time value.
    explicit Stale(my_context ctx) : my_base(ctx) {
        NdpEntry *state_machine = &context<NdpEntry>();
        state_machine->set_state(NdpEntry::STALE);
    }

    // Cancel the hold timer.  If we go to Established, the timer will get
    // started again from the constructor for that state.
    ~Stale() {
    }

    // If different mac then move to stale
    sc::result react(const EvNsIn &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        if (state_machine->mac() != event.mac_) {
            state_machine->set_mac(event.mac_);
        }
        return discard_event();
    }

    // If different mac then move to stale else unchanged
    sc::result react(const EvUnsolNaIn &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        if (event.na_->nd_na_flags_reserved & ND_NA_FLAG_OVERRIDE) {
            if (state_machine->mac() != event.mac_) {
                state_machine->set_mac(event.mac_);
                return transit<Stale>();
            }
        }
        return discard_event();
    }


    // If same mac then move to reachable else unchanged
    sc::result react(const EvSolNaIn &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        if (event.na_->nd_na_flags_reserved & ND_NA_FLAG_OVERRIDE) {
            if (state_machine->mac() != event.mac_) {
                state_machine->set_mac(event.mac_);
            }
            return transit<Reachable>();
        }
        return discard_event();
    }

    // start delay timer and move to delay
    sc::result react(const EvPktOut &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        state_machine->StartDelayTimer();
        return transit<Delay>();
    }

    sc::result react(const EvTestStateChange &event) {
        NdpEntry::State state = event.state_;
        NdpEntry *state_machine = &context<NdpEntry>();
        state_machine->set_state(state);
        state_machine->set_mac(MacAddress());
        state_machine->retry_count_set(event.retry_);
        switch (state) {
            case NdpEntry::NOSTATE: return transit<NoState>();
            case NdpEntry::INCOMPLETE: return transit<Incomplete>();
            case NdpEntry::REACHABLE: return transit<Reachable>();
            case NdpEntry::STALE: return transit<Stale>();
            case NdpEntry::DELAY: return transit<Delay>();
            case NdpEntry::PROBE: return transit<Probe>();
            default: return discard_event();
        }
    }
};

//
// Established is the final state for an operation peer.
//
struct Delay : sc::state<Delay, NdpEntry> {
    typedef mpl::list<
        sc::custom_reaction<EvNsIn>,
        sc::custom_reaction<EvUnsolNaIn>,
        sc::custom_reaction<EvSolNaIn>,
        sc::custom_reaction<EvDelayTimerExpired>,
        sc::custom_reaction<EvTestStateChange>
    > reactions;

    explicit Delay(my_context ctx) : my_base(ctx) {
        NdpEntry *state_machine = &context<NdpEntry>();
        state_machine->retry_count_clear();
        state_machine->set_state(NdpEntry::DELAY);
    }

    ~Delay() {
    }

    // If different mac then move to stale
    sc::result react(const EvNsIn &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        if (state_machine->mac() != event.mac_) {
            state_machine->set_mac(event.mac_);
            return transit<Stale>();
        }
        return discard_event();
    }


    // If different mac then move to stale else unchanged
    sc::result react(const EvUnsolNaIn &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        if (event.na_->nd_na_flags_reserved & ND_NA_FLAG_OVERRIDE) {
            if (state_machine->mac() != event.mac_) {
                state_machine->set_mac(event.mac_);
                return transit<Stale>();
            }
        }
        return discard_event();
    }


    // If same mac then move to reachable else unchanged
    sc::result react(const EvSolNaIn &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        if (event.na_->nd_na_flags_reserved & ND_NA_FLAG_OVERRIDE) {
            if (state_machine->mac() != event.mac_) {
                state_machine->set_mac(event.mac_);
            }
            return transit<Reachable>();
        }
        return discard_event();
    }

    // Send unicast NS probe and start retransmit timer
    sc::result react(const EvDelayTimerExpired &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        // In UTs, ndp_entry may not be there
        if (state_machine->get_interface())
            state_machine->SendNeighborSolicit();
        state_machine->StartRetransmitTimer();
        return transit<Probe>();
    }

    sc::result react(const EvTestStateChange &event) {
        NdpEntry::State state = event.state_;
        NdpEntry *state_machine = &context<NdpEntry>();
        state_machine->set_state(state);
        state_machine->set_mac(MacAddress());
        switch (state) {
            case NdpEntry::NOSTATE: return transit<NoState>();
            case NdpEntry::INCOMPLETE: return transit<Incomplete>();
            case NdpEntry::REACHABLE: return transit<Reachable>();
            case NdpEntry::STALE: return transit<Stale>();
            case NdpEntry::DELAY: return transit<Delay>();
            case NdpEntry::PROBE: return transit<Probe>();
            default: return discard_event();
        }
    }
};

//
// Established is the final state for an operation peer.
//
struct Probe : sc::state<Probe, NdpEntry> {
    typedef mpl::list<
        sc::custom_reaction<EvNsIn>,
        sc::custom_reaction<EvUnsolNaIn>,
        sc::custom_reaction<EvSolNaIn>,
        sc::custom_reaction<EvRetransmitTimerExpired>,
        sc::custom_reaction<EvDelayTimerExpired>,
        sc::custom_reaction<EvTestStateChange>
    > reactions;

    explicit Probe(my_context ctx) : my_base(ctx) {
        NdpEntry *state_machine = &context<NdpEntry>();
        state_machine->retry_count_clear();
        state_machine->set_state(NdpEntry::PROBE);
    }

    ~Probe() {
    }

    // If different mac then move to stale
    sc::result react(const EvNsIn &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        if (state_machine->mac() != event.mac_) {
            state_machine->set_mac(event.mac_);
            return transit<Stale>();
        }
        return discard_event();
    }


    // If different mac then move to stale else unchanged
    sc::result react(const EvUnsolNaIn &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        if (event.na_->nd_na_flags_reserved & ND_NA_FLAG_OVERRIDE) {
            if (state_machine->mac() != event.mac_) {
                state_machine->set_mac(event.mac_);
                return transit<Stale>();
            }
        }
        return discard_event();
    }


    // If same mac then move to reachable else unchanged
    sc::result react(const EvSolNaIn &event) {
        if (event.na_->nd_na_flags_reserved & ND_NA_FLAG_OVERRIDE) {
            NdpEntry *state_machine = &context<NdpEntry>();
            if (state_machine->mac() != event.mac_) {
                state_machine->set_mac(event.mac_);
            }
            return transit<Reachable>();
        }
        return discard_event();
    }

    // If less than N retransmissions then retransmit and restart timer
    // Else discard entry 
    sc::result react(const EvDelayTimerExpired &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        // In UTs, ndp_entry may not be there
        if (state_machine->get_interface())
            state_machine->SendNeighborSolicit();
        state_machine->StartRetransmitTimer();
        return transit<Probe>();
    }

    // If more than N then stale
    sc::result react(const EvRetransmitTimerExpired &event) {
        NdpEntry *state_machine = &context<NdpEntry>();
        if (state_machine->retry_count() < NdpEntry::kMaxRetries) {
            if (state_machine->get_interface())
                state_machine->SendNeighborSolicit();
            state_machine->StartRetransmitTimer();
            return discard_event();
        } else {
            if (state_machine->DeleteNdpRoute())
                return discard_event();
            state_machine->retry_count_clear();
        }
        return discard_event();
    }

    sc::result react(const EvTestStateChange &event) {
        NdpEntry::State state = event.state_;
        NdpEntry *state_machine = &context<NdpEntry>();
        state_machine->set_state(state);
        state_machine->set_mac(MacAddress());
        switch (state) {
            case NdpEntry::NOSTATE: return transit<NoState>();
            case NdpEntry::INCOMPLETE: return transit<Incomplete>();
            case NdpEntry::REACHABLE: return transit<Reachable>();
            case NdpEntry::STALE: return transit<Stale>();
            case NdpEntry::DELAY: return transit<Delay>();
            case NdpEntry::PROBE: return transit<Probe>();
            default: return discard_event();
        }
    }
};

}  // namespace fsm

NdpEntry::NdpEntry(boost::asio::io_service &io, Icmpv6Handler *handler,
                   NdpKey &key, const VrfEntry *vrf, const Interface *itf)
    : work_queue_(TaskScheduler::GetInstance()->GetTaskId("Agent::Services"),
      NULL,
      boost::bind(&NdpEntry::DequeueEvent, this, _1)),
      delay_timer_(TimerManager::CreateTimer(
                  io, "Delay timer",
                  TaskScheduler::GetInstance()->GetTaskId("Agent::Services"),
                  PktHandler::ICMPV6)),
      retransmit_timer_(TimerManager::CreateTimer(
                  io, "Retransmit timer",
                  TaskScheduler::GetInstance()->GetTaskId("Agent::Services"),
                  PktHandler::ICMPV6)),
      reachable_timer_(TimerManager::CreateTimer(
                  io, "Reachable timer",
                  TaskScheduler::GetInstance()->GetTaskId("Agent::Services"),
                  PktHandler::ICMPV6)),
      retransmit_time_(1000),
      delay_time_(5000),
      reachable_time_(30000),
      retry_count_(0),
      deleted_(false),
      state_(NOSTATE),
      last_state_(NOSTATE),
      io_(io), key_(key), nh_vrf_(vrf), handler_(handler), interface_(itf) {
    initiate();
}

NdpEntry::~NdpEntry() {
    work_queue_.Shutdown();
    terminate();
    DeleteAllTimers();
    if (handler_.get())
        handler_.reset(NULL);
}

void NdpEntry::DeleteAllTimers() {
    TimerManager::DeleteTimer(delay_timer_);
    TimerManager::DeleteTimer(retransmit_timer_);
    TimerManager::DeleteTimer(reachable_timer_);
}

void NdpEntry::StartDelayTimer() {
    if (delay_time_ <= 0)
        return;

    delay_timer_->Cancel();
    delay_timer_->Start(delay_time_,
        boost::bind(&NdpEntry::DelayTimerExpired, this), NULL);
}

void NdpEntry::StartReachableTimer() {
    if (reachable_time_ <= 0)
        return;

    reachable_timer_->Cancel();
    reachable_timer_->Start(reachable_time_,
        boost::bind(&NdpEntry::ReachableTimerExpired, this), NULL);
}

bool NdpEntry::ReachableTimerExpired() {
    Enqueue(fsm::EvReachableTimerExpired());
    return false;
}

void NdpEntry::StartRetransmitTimer() {
    if (retransmit_time_ <= 0)
        return;

    retry_count_inc();
    retransmit_timer_->Cancel();
    retransmit_timer_->Start(retransmit_time_,
        boost::bind(&NdpEntry::RetransmitTimerExpired, this), NULL);
}

bool NdpEntry::RetransmitTimerExpired() {
    Enqueue(fsm::EvRetransmitTimerExpired());
    return false;
}

bool NdpEntry::DelayTimerExpired() {
    Enqueue(fsm::EvDelayTimerExpired());
    return false;
}

bool NdpEntry::EnqueuePktOut() {
    Enqueue(fsm::EvPktOut());
    return false;
}
bool NdpEntry::EnqueueRetransmitTimerExpired() {
    Enqueue(fsm::EvRetransmitTimerExpired());
    return false;
}
bool NdpEntry::EnqueueDelayTimerExpired() {
    Enqueue(fsm::EvDelayTimerExpired());
    return false;
}
bool NdpEntry::EnqueueNsIn(nd_neighbor_solicit *ns, MacAddress mac) {
    Enqueue(fsm::EvNsIn(ns, mac));
    return false;
}
bool NdpEntry::EnqueueNaIn(nd_neighbor_advert *na, MacAddress mac) {
    if (na->nd_na_flags_reserved & ND_NA_FLAG_SOLICITED) {
        Enqueue(fsm::EvSolNaIn(na, mac));
    } else {
        Enqueue(fsm::EvUnsolNaIn(na, mac));
    }
    return false;
}

bool NdpEntry::EnqueueUnsolNaIn(nd_neighbor_advert *na, MacAddress mac) {
    Enqueue(fsm::EvUnsolNaIn(na, mac));
    return false;
}

bool NdpEntry::EnqueueSolNaIn(nd_neighbor_advert *na, MacAddress mac) {
    Enqueue(fsm::EvSolNaIn(na, mac));
    return false;
}

bool NdpEntry::EnqueueTestStateChange(State state, int retry_count) {
    Enqueue(fsm::EvTestStateChange(state, retry_count));
    return false;
}

static const string state_names[] = {
    "NoState",
    "Incomplete",
    "Reachable",
    "Stale",
    "Delay",
    "Probe"
};

const string &NdpEntry::StateName() const {
    return state_names[state_];
}

const string &NdpEntry::LastStateName() const {
    return state_names[last_state_];
}

const string NdpEntry::last_state_change_at() const {
    return integerToString(UTCUsecToPTime(last_state_change_at_));
}

const uint64_t NdpEntry::last_state_change_usecs_at() const {
    return last_state_change_at_;
}

ostream &operator<<(ostream &out, const NdpEntry::State &state) {
    out << state_names[state];
    return out;
}

// This class determines whether a given class has a method called 'validate'.
template <typename Ev>
struct HasValidate {
    template <typename T, bool (T::*)(NdpEntry *) const> struct SFINAE {};
    template <typename T> static char Test(SFINAE<T, &T::validate>*);
    template <typename T> static int Test(...);
    static const bool Has = sizeof(Test<Ev>(0)) == sizeof(char);
};

template <typename Ev, bool has_validate>
struct ValidateFn {
    EvValidate operator()(const Ev *event) {
        return NULL;
    }
};

template <typename Ev>
struct ValidateFn<Ev, true> {
    EvValidate operator()(const Ev *event) {
        return boost::bind(&Ev::validate, event, _1);
    }
};

template <typename Ev>
bool NdpEntry::Enqueue(const Ev &event) {
    LogEvent(TYPE_NAME(event), "Enqueue");
    EventContainer ec;
    ec.event = event.intrusive_from_this();
    ec.validate = ValidateFn<Ev, HasValidate<Ev>::Has>()(
        static_cast<const Ev *>(ec.event.get()));
    work_queue_.Enqueue(ec);

    return true;
}

void NdpEntry::LogEvent(string event_name, string msg,
                            SandeshLevel::type log_level) {
    // Reduce log level for keepalive and update messages.
    if (get_state() == REACHABLE) {
        log_level = Sandesh::LoggingUtLevel();
    }
    SM_LOG(log_level, msg << " " << event_name << " in state " << StateName());
}

bool NdpEntry::DequeueEvent(NdpEntry::EventContainer ec) {
    set_last_event(TYPE_NAME(*ec.event));
    if (ec.validate.empty() || ec.validate(this)) {
        //LogEvent(TYPE_NAME(*ec.event), "Dequeue");
        process_event(*ec.event);
    //} else {
        //LogEvent(TYPE_NAME(*ec.event), "Discard", SandeshLevel::SYS_INFO);
    }
    ec.event.reset();

    return true;
}

void NdpEntry::DequeueEventDone(bool done) {
}

void NdpEntry::set_last_event(const std::string &event) {
    last_event_ = event;
    last_event_at_ = UTCTimestampUsec();
}

void NdpEntry::set_last_notification_out(int code, int subcode,
    const string &reason) {
    last_notification_out_ = std::make_pair(code, subcode);
    last_notification_out_at_ = UTCTimestampUsec();
    last_notification_out_error_ = reason;

}

void NdpEntry::set_last_notification_in(int code, int subcode,
    const string &reason) {
    last_notification_in_ = std::make_pair(code, subcode);
    last_notification_in_at_ = UTCTimestampUsec();
    last_notification_in_error_ = reason;

}

void NdpEntry::set_state(State state) {
    if (state == state_)
        return;
    last_state_ = state_; state_ = state;
    last_state_change_at_ = UTCTimestampUsec();

}

void NdpEntry::reset_last_info() {
    last_notification_in_ = std::make_pair(0, 0);
    last_notification_in_at_ = 0;
    last_notification_in_error_ = std::string();
    last_notification_out_ = std::make_pair(0, 0);
    last_notification_out_at_ = 0;
    last_notification_out_error_ = std::string();
    last_state_ = NOSTATE;
    last_event_ = "";
    last_state_change_at_ = 0;
    last_event_at_ = 0;

}
bool NdpEntry::IsResolved() {
    return (get_state() != (NdpEntry::NOSTATE) &&
            get_state() != (NdpEntry::INCOMPLETE));
}

bool NdpEntry::IsDerived() {
    return false;
    if (key_.vrf != nh_vrf_) {
        return true;
    }
    return false;
}

void NdpEntry::SendNeighborSolicit(bool send_unicast) {
    assert(!IsDerived());
    Agent *agent = handler_->agent();
    uint32_t vrf_id = VrfEntry::kInvalidIndex;
    IpAddress ip;
    const VmInterface *vmi = NULL;
    if (interface_->type() == Interface::VM_INTERFACE) {
        vmi = static_cast<const VmInterface *>(interface_.get());
        ip = vmi->GetServiceIp(key_.ip);
        if (vmi->vmi_type() == VmInterface::VHOST) {
            ip = agent->router_id();
        }
        vrf_id = nh_vrf_->vrf_id();
    } else {
        ip = agent->router_id();
        VrfEntry *vrf =
            agent->vrf_table()->FindVrfFromName(agent->fabric_vrf_name());
        if (vrf) {
            vrf_id = vrf->vrf_id();
        }
    }

    if (vrf_id != VrfEntry::kInvalidIndex) {
        if (ip.is_v4()) {
            handler_->SendNeighborSolicit(Ip6Address::v4_mapped(ip.to_v4()), key_.ip,
                                          vmi, vrf_id, send_unicast);
        } else {
            handler_->SendNeighborSolicit(ip.to_v6(), key_.ip,
                                          vmi, vrf_id, send_unicast);
        }
    }
}

void NdpEntry::SendNeighborAdvert(bool solicited) {
    assert(!IsDerived());
    Agent *agent = handler_->agent();
    IpAddress ip;
    const VmInterface *vmi = NULL;
    if (interface_->type() == Interface::VM_INTERFACE) {
        vmi = static_cast<const VmInterface *>(interface_.get());
        MacAddress smac = vmi->GetVifMac(agent);
        if (key_.vrf && key_.vrf->vn()) {
            IpAddress gw_ip = key_.vrf->vn()->GetGatewayFromIpam
                    (Ip6Address(key_.ip));
            IpAddress dns_ip = key_.vrf->vn()->GetDnsFromIpam
                    (Ip6Address(key_.ip));
            if (!gw_ip.is_unspecified() && gw_ip.is_v6())  {
                handler_->SendNeighborAdvert(gw_ip.to_v6(), key_.ip,
                                             smac, vmi->vm_mac(), vmi->id(),
                                             key_.vrf->vrf_id(), solicited);
            }
            if (!dns_ip.is_unspecified() && dns_ip.is_v6() && dns_ip != gw_ip) {
                handler_->SendNeighborAdvert(dns_ip.to_v6(), key_.ip,
                                             smac, vmi->vm_mac(), vmi->id(),
                                             key_.vrf->vrf_id(), solicited);
            }
        }
    } else {
        if (agent->router_id6().is_v6()) {
            handler_->SendNeighborAdvert(agent->router_id6().to_v6(), key_.ip,
                 agent->icmpv6_proto()->ip_fabric_interface_mac(),
                 MacAddress(),
                 agent->icmpv6_proto()->ip_fabric_interface_index(),
                 key_.vrf->vrf_id(), solicited);
        }
    }
}

void NdpEntry::HandleNsRequest(nd_neighbor_solicit *ns, MacAddress mac) {
    if (IsResolved())
        AddNdpRoute(true);
    else {
        AddNdpRoute(false);
    }
    EnqueueNsIn(ns, mac);
}

void NdpEntry::AddNdpRoute(bool resolved) {
    if (key_.vrf->GetName() == handler_->agent()->linklocal_vrf_name()) {
        // Do not squash existing route entry.
        // should be smarter and not replace an existing route.
        return;
    }

    Ip6Address ip(key_.ip);
    const string& vrf_name = key_.vrf->GetName();
    NdpNHKey nh_key(nh_vrf_->GetName(), ip, false);
    NdpNH *ndp_nh = static_cast<NdpNH *>(handler_->agent()->nexthop_table()->
                                         FindActiveEntry(&nh_key));

    if (ndp_nh && ndp_nh->GetResolveState() &&
        mac().CompareTo(ndp_nh->GetMac()) == 0) {
        // MAC address unchanged, ignore
        if (!IsDerived()) {
            return;
        } else {
            /* Return if the route is already existing */
            InetUnicastRouteKey *rt_key = new InetUnicastRouteKey(
                    handler_->agent()->local_peer(), vrf_name, ip, 32);
            AgentRoute *entry = key_.vrf->GetInet4UnicastRouteTable()->
                FindActiveEntry(rt_key);
            delete rt_key;
            if (entry) {
                return;
            }
            resolved = true;
        }
    }

    NDP_TRACE(Trace, "Add", ip.to_string(), vrf_name, mac().ToString());
    AgentRoute *entry = key_.vrf->GetInet6UnicastRouteTable()->FindLPM(ip);

    bool policy = false;
    SecurityGroupList sg;
    TagList tag;
    VnListType vn_list;
    if (entry) {
        policy = entry->GetActiveNextHop()->PolicyEnabled();
        sg = entry->GetActivePath()->sg_list();
        tag = entry->GetActivePath()->tag_list();
        vn_list = entry->GetActivePath()->dest_vn_list();
    }

    const Interface *itf = handler_->agent()->icmpv6_proto()->ip_fabric_interface();
    if (interface_->type() == Interface::VM_INTERFACE) {
        const VmInterface *vintf =
            static_cast<const VmInterface *>(interface_.get());
        if (vintf->vmi_type() == VmInterface::VHOST) {
            itf = vintf->parent();
        }
    }

    handler_->agent()->fabric_inet4_unicast_table()->NdpRoute(
                       DBRequest::DB_ENTRY_ADD_CHANGE, vrf_name, ip, mac(),
                       nh_vrf_->GetName(), *itf, resolved, 128, policy,
                       vn_list, sg, tag);
}

bool NdpEntry::DeleteNdpRoute() {
    if (key_.vrf->GetName() == handler_->agent()->linklocal_vrf_name()) {
        return true;
    }

    Ip6Address ip(key_.ip);
    const string& vrf_name = key_.vrf->GetName();
    NdpNHKey nh_key(nh_vrf_->GetName(), ip, false);
    NdpNH *ndp_nh = static_cast<NdpNH *>(handler_->agent()->nexthop_table()->
                                         FindActiveEntry(&nh_key));
    if (!ndp_nh)
        return true;

    NDP_TRACE(Trace, "Delete", ip.to_string(), vrf_name, mac().ToString());
    if (IsDerived()) {
        //Just enqueue a delete, no need to mark nexthop invalid
        InetUnicastAgentRouteTable::Delete(handler_->agent()->local_peer(),
                                           vrf_name, ip, 32);
        return true;
    }

    handler_->agent()->fabric_inet4_unicast_table()->NdpRoute(
                       DBRequest::DB_ENTRY_DELETE, vrf_name, ip, mac(),
                       nh_vrf_->GetName(), *interface_, false, 128, false,
                       Agent::NullStringList(), SecurityGroupList(), TagList());
    return false;
}

void NdpEntry::Resync(bool policy, const VnListType &vnlist,
                      const SecurityGroupList &sg,
                      const TagList &tag) {
    Ip6Address ip(key_.ip);
    const string& vrf_name = key_.vrf->GetName();
    NDP_TRACE(Trace, "Resync", ip.to_string(), vrf_name,
              mac().ToString());
    handler_->agent()->fabric_inet4_unicast_table()->NdpRoute(
                       DBRequest::DB_ENTRY_ADD_CHANGE, key_.vrf->GetName(), ip,
                       mac(), nh_vrf_->GetName(), *interface_, IsResolved(),
                       32, policy, vnlist, sg, tag);
}
