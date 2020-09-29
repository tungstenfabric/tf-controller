/*
 * Copyright (c) 2017 Juniper Networks, Inc. All rights reserved.
 */

#ifndef vnsw_agent_bfd_proto_h_
#define vnsw_agent_bfd_proto_h_

#include "pkt/proto.h"
#include "pkt/pkt_handler.h"
#include "services/bfd_handler.h"
#include "oper/health_check.h"

#include "bfd/bfd_client.h"
#include "bfd/bfd_server.h"
#include "bfd/bfd_connection.h"
#include "bfd/bfd_session.h"

#include "base/test/task_test_util.h"

#define BFD_TX_BUFF_LEN 128

#define BFD_TRACE(obj, ...)                                                 \
do {                                                                        \
    Bfd##obj::TraceMsg(BfdTraceBuf, __FILE__, __LINE__, ##__VA_ARGS__);     \
} while (false)

class BfdSessionsKey {
public:
    BfdSessionsKey(uint32_t id, IpAddress ip) :
        id_(id), ip_(ip) {
    }

    ~BfdSessionsKey () { }

    bool operator<(const BfdSessionsKey &right) const {
        if ( id_ == right.id_ ) {
            return ip_ < right.ip_;
        } else {
            return id_ < right.id_;
        }
    }

    bool IsLess(const BfdSessionsKey &rhs) const;
    bool IsEqual(const BfdSessionsKey &rhs) const;

    uint32_t id_;
    IpAddress ip_;
};

struct BfdSessionsKeyCmp {
    bool operator()(const BfdSessionsKey &lhs, const BfdSessionsKey &rhs) const {
        return lhs.IsLess(rhs);
    }
};

class BfdProto : public Proto {
public:
    static const uint32_t kMultiplier = 2;
    static const uint32_t kMinRxInterval = 500000; // microseconds
    static const uint32_t kMinTxInterval = 500000; // microseconds

    struct BfdStats {
        BfdStats() { Reset(); }
        void Reset() { bfd_sent = bfd_received = bfd_rx_drop_count = 0;
                       bfd_rx_ka_enqueue_count = 0; }

        uint64_t bfd_sent;
        uint64_t bfd_received;
        uint32_t bfd_rx_drop_count;
        uint64_t bfd_rx_ka_enqueue_count;
    };

    class BfdCommunicator : public BFD::Connection {
    public:
        BfdCommunicator(BfdProto *bfd_proto) :
            bfd_proto_(bfd_proto), server_(NULL) {}
        virtual ~BfdCommunicator() {}
        virtual void SendPacket(
                const boost::asio::ip::udp::endpoint &local_endpoint,
                const boost::asio::ip::udp::endpoint &remote_endpoint,
                const BFD::SessionIndex &session_index,
                const boost::asio::mutable_buffer &packet, int pktSize);
        virtual void NotifyStateChange(const BFD::SessionKey &key, const bool &up);
        virtual BFD::Server *GetServer() const { return server_; }
        virtual void SetServer(BFD::Server *server) { server_ = server; }

    private:
        BfdProto *bfd_proto_;
        BFD::Server *server_;
    };

    BfdProto(Agent *agent, boost::asio::io_service &io);
    virtual ~BfdProto();
    ProtoHandler *AllocProtoHandler(boost::shared_ptr<PktInfo> info,
                                    boost::asio::io_service &io);
    void Shutdown() {
        delete client_;
        client_ = NULL;

        // server_->DeleteClientSessions();
        // TASK_UTIL_EXPECT_TRUE(server_->event_queue()->IsQueueEmpty());
        server_->event_queue()->Shutdown();
        delete server_;
        server_ = NULL;

        sessions_.clear();
    }

    bool Enqueue(boost::shared_ptr<PktInfo> msg);
    void ProcessStats(PktStatsType::Type type);
    bool ProcessBfdKeepAlive(boost::shared_ptr<PktInfo> msg);
    void HandleReceiveSafe(boost::asio::const_buffer pkt,
                       const boost::asio::ip::udp::endpoint &local_endpoint,
                       const boost::asio::ip::udp::endpoint &remote_endpoint,
                       const BFD::SessionIndex &session_index,
                       uint8_t pkt_len,
                       boost::system::error_code ec);

    bool BfdHealthCheckSessionControl(
               HealthCheckTable::HealthCheckServiceAction action,
               HealthCheckInstanceService *service);
    void NotifyHealthCheckInstanceService(uint32_t interface,
                IpAddress address, std::string &data);
    BfdCommunicator &bfd_communicator() { return communicator_; }

    void IncrementSent() { stats_.bfd_sent++; }
    void IncrementReceived() { stats_.bfd_received++; }
    void IncrementReceiveDropCount() { stats_.bfd_rx_drop_count++; }
    void IncrementKaEnqueueCount() { stats_.bfd_rx_ka_enqueue_count++; }
    const BfdStats &GetStats() const { return stats_; }
    uint32_t ActiveSessions() const { return sessions_.size(); }

private:
    friend BfdCommunicator;
    // map from interface id,dest-ip to health check instance service
    typedef std::map<BfdSessionsKey, HealthCheckInstanceService *, BfdSessionsKeyCmp> Sessions;
    typedef std::pair<BfdSessionsKey, HealthCheckInstanceService *> SessionsPair;

    tbb::mutex mutex_; // lock for sessions_ access between health check & BFD
    tbb::mutex rx_mutex_; // lock for BFD control & keepalive Rx data
    boost::shared_ptr<PktInfo> msg_;
    BfdCommunicator communicator_;
    BFD::Server *server_;
    BFD::Client *client_;
    BfdHandler handler_;
    Sessions sessions_;
    BfdStats stats_;

    DISALLOW_COPY_AND_ASSIGN(BfdProto);
};

#endif // vnsw_agent_bfd_proto_h_
