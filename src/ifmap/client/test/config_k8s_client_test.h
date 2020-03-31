/*
 * Copyright (c) 2018 Juniper Networks, Inc. All rights reserved.
 */
#ifndef ctrlplane_config_k8s_client_test_h
#define ctrlplane_config_k8s_client_test_h

#include <boost/foreach.hpp>
#include <fstream>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <vector>
#include "config-client-mgr/config_cass2json_adapter.h"
#include "config-client-mgr/config_client_manager.h"
#include "config-client-mgr/config_k8s_client.h"
#include "config-client-mgr/config_factory.h"
#include "database/k8s/k8s_client.h"
#include "ifmap/client/config_json_parser.h"
#include "rapidjson/document.h"
#include "rapidjson/stringbuffer.h"
#include "rapidjson/writer.h"

using namespace std;
using std::string;
using k8s::client::K8sClient;
using k8s::client::K8sUrl;
using k8s::client::DomPtr;
using k8s::client::GetCb;
using contrail_rapidjson::StringBuffer;
using contrail_rapidjson::Writer;

static int num_bunch = 8;
static int max_yield = 4;
static Document dbDoc_;
static int db_index = 2;

class K8sClientTest : public K8sClient {
public:
    K8sClientTest(const std::vector<K8sUrl> &k8sUrls,
                  const std::string &caCerts,
                  size_t rotate,
                  size_t fetchLimit)
        : K8sClient(k8sUrls, caCerts, rotate, fetchLimit)
    {}

    virtual int Init() 
    { 
        // Populate info on supported kinds (needed to support bulk get).
        KindInfo kindInfo;
        vector<std::string> kinds;
        kinds.push_back("BgpAsAService");
        kinds.push_back("VirtualMachineInterface");
        kinds.push_back("VirtualNetwork");
        for (size_t i = 0; i < kinds.size(); ++i)
        {
            std::string kind = kinds[i];
            kindInfo.kind = kind;
            kindInfoMap_[kind] = kindInfo;            
        }
        return 0; 
    }

    virtual int BulkGet(const std::string &kind, GetCb getCb)
    {
        if (--db_index == 0) {
            return 400;
        }
        
        /**
          * Make sure the database document is populated.
          */

        /* Bulk data is one big document with an "items" member. */
        Value& items = dbDoc_["items"];

        for (Value::ConstValueIterator itr = items.Begin();
             itr != items.End(); itr++) {
            
            /**
              * Get the uuid string and the value from the
              * database Document created from the input file.
              */
            DomPtr domPtr(new Document);
            domPtr->CopyFrom(*itr, domPtr->GetAllocator());

            /**
              * Invoke the callback.
              */
            getCb(domPtr);
        }

        return 200;
    }

    static void ParseDatabase(string db_file) {
        string json_db = FileRead(db_file);
        assert(json_db.size() != 0);

        Document *dbDoc = &dbDoc_;
        dbDoc->Parse<0>(json_db.c_str());
        if (dbDoc->HasParseError()) {
            size_t pos = dbDoc->GetErrorOffset();
            // GetParseError returns const char *
            std::cout << "Error in parsing JSON DB at "
                << pos << "with error description"
                << dbDoc->GetParseError()
                << std::endl;
            exit(-1);
        }
        task_util::WaitForIdle();
    }

    static string FileRead(const string &filename) {
        ifstream file(filename.c_str());
        string content((istreambuf_iterator<char>(file)),
                       istreambuf_iterator<char>());
        return content;
    }
};

class ConfigK8sClientTest : public ConfigK8sClient {
public:
    ConfigK8sClientTest(
             ConfigClientManager *mgr,
             EventManager *evm,
             const ConfigClientOptions &options,
             int num_workers) :
                   ConfigK8sClient(mgr,
                                    evm,
                                    options,
                                    num_workers),
                   cevent_(0) {
    }

    Document *ev_load() { return &evDoc_; }

    // All the test data consists of an array of objects.
    void ParseEventsJson(string events_file) 
    {
        string json_events = FileRead(events_file);
        assert(json_events.size() != 0);

        Document *eventDoc = &evDoc_;
        eventDoc->Parse<0>(json_events.c_str());
        if (eventDoc->HasParseError()) {
            size_t pos = eventDoc->GetErrorOffset();
            // GetParseError returns const char *
            std::cout << "Error in parsing JSON events at "
                << pos << "with error description"
                << eventDoc->GetParseError()
                << std::endl;
            exit(-1);
        }
    }

    void FeedEventsJson() 
    {
        // Each event is a nested document.  Skip to the next one to be read.
        Value::Array events = evDoc_.GetArray();

        // trivial case, simply return
        if (events.Empty()) {
            return;
        }

        while (cevent_ < events.Size())
        {
            /**
              * Get the uuid string and the value from the
              * database Document created from the input file.
              */
            Value event = events[cevent_++].GetObject();
            Value::MemberIterator type = event.FindMember("type");
            string type_str = type->value.GetString();

            Value::MemberIterator metadata;
            Value::MemberIterator uid;
            string uid_str;

            if (type_str == "PAUSED") {
                break;
            }
            
            Value::MemberIterator object = event.FindMember("object");
            DomPtr domPtr(new Document);
            domPtr->CopyFrom(object->value, domPtr->GetAllocator());

            ConfigK8sClient::ProcessResponse(type_str, domPtr);
        }
        task_util::WaitForIdle();
    }

    static string FileRead(const string &filename) {
        return (K8sClientTest::FileRead(filename));
    }

private:
    virtual uint32_t GetNumUUIDRequestToBunch() const {
        return num_bunch;
    }

    virtual const int GetMaxRequestsToYield() const {
        return max_yield;
    }

    Document evDoc_;
    size_t cevent_;
};

class ConfigClientManagerMock : public ConfigClientManager {
public:
    ConfigClientManagerMock(
                   EventManager *evm,
                   string hostname,
                   string module_name,
                   const ConfigClientOptions& config_options) :
             ConfigClientManager(evm,
                                 hostname,
                                 module_name,
                                 config_options) {
    }
};
#endif
