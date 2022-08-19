/*
 * Copyright (c) 2013 Juniper Networks, Inc. All rights reserved.
 */

#ifndef vnsw_agent_icmp_proto_h_
#define vnsw_agent_icmp_proto_h_

#include "pkt/proto.h"
#include "services/icmp_handler.h"

class IcmpProto : public Proto {
public:
    struct IcmpStats {
        IcmpStats() { Reset(); }
        void Reset() { icmp_gw_ping = icmp_gw_ping_err = icmp_drop =
                        icmp_intf_not_inst = icmp_no_l3fwd = 0; }

        uint32_t icmp_gw_ping;
        uint32_t icmp_gw_ping_err;
        uint32_t icmp_drop;
        uint32_t icmp_intf_not_inst;
        uint32_t icmp_no_l3fwd;
    };

    void Shutdown() {}
    IcmpProto(Agent *agent, boost::asio::io_service &io);
    virtual ~IcmpProto();
    ProtoHandler *AllocProtoHandler(boost::shared_ptr<PktInfo> info,
                                    boost::asio::io_service &io);

    void IncrStatsGwPing() { stats_.icmp_gw_ping++; }
    void IncrStatsGwPingErr() { stats_.icmp_gw_ping_err++; }
    void IncrStatsDrop() { stats_.icmp_drop++; }
    void IncrStatsIntfNotInst() { stats_.icmp_intf_not_inst++; }
    void IncrStatsNoL3Fwd() { stats_.icmp_no_l3fwd++; }
    const IcmpStats &GetStats() const { return stats_; }
    void ClearStats() { stats_.Reset(); }

private:
    IcmpStats stats_;
    DISALLOW_COPY_AND_ASSIGN(IcmpProto);
};

#endif // vnsw_agent_icmp_proto_h_
