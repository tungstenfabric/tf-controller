# Purpose: Filter to generate Kubernetes JSON data from ETCD JSON data.
# Author:  Edwin P. Jacques (ejacques@juniper.net)
# Copyright (c) 2020 Juniper Networks, Inc. All rights reserved.

# Convert type_name into CamelCase
def type_case:
  if test("global-system-config") then "GlobalSystemConfig" else 
  (split("_") 
    | map((.[0:1] | ascii_upcase) + .[1:]) 
    | join("")
  )
  end;

# Convert field_name into camelCase
def field_case:
  . | type_case 
    | (.[0:1] | ascii_downcase) + .[1:];

# For a given value key/value, recurse to fix the field names
def recurse_field_case:
  . | with_entries(.key |= field_case)
    | with_entries(.value |= 
          if (type == "object")
          then (recurse_field_case) 
          else . 
          end);

# Update refs properly to:
# 1.) use camelCase naming
# 2.) rename attr to attribute
# 3.) rename uuid to uid
def ref_data:
  . | recurse_field_case
    | with_entries(
      .value |= 
        map(with_entries(.key |= 
          if test("attr") then "attributes" 
          elif test("uuid") then "uid"
          else . end)
        )
      );

# Create key/value pairs for all fields in the spec.
# filter out any refs
def spec_data:
  . | del(.id_perms)
    | del(.perms2) 
    | del(.type) 
    | del(.uuid)
    | del(.event)
    | if (.parent_uuid != null) then
        . +
        { "parent": {
              "apiVersion": "core.contrail.juniper.net/v1alpha1",
              "kind": .parent_type | type_case,
              "uid": .parent_uuid
            }
        }
      else 
        .
      end
    | del(.parent_type)
    | del(.parent_uuid)
    | del(.parent_name)
    | ( [ to_entries | .[] | select(.key | endswith("_refs") | not) ] | from_entries )
    | recurse_field_case;

# Create status including refs if needed.
# Look for parent ref and add it if it exists.
# Find all keys with "_refs" at the end and create ref entry. 
# Finally, add the status
def status_data:
  . | del(.fq_name)
    | del(.parent_type)
    | del(.parent_uuid)
    | del(.parent_name)
    |   {"state": "Success"}
      + ( [ to_entries | .[] | select(.key | endswith("_refs")) | .key = (.key | sub("_refs";"_references")) ] | from_entries | ref_data)
    ;

# Convert etcd database event list into a list of Kubernetes watch objects.
def watch_etcd_to_k8s:
[
  .[] | 
        (
          ((.event | split("/")) + [.])
          |
            if (.[1] == "PAUSED") then
              {"type": .[1]} 
            else
              {"type": ((select(.[1] == "CREATE") | "ADDED")
                      , (select(.[1] == "UPDATE") | "MODIFIED")
                      , (select(.[1] == "DELETE") | "DELETED"))} 
              + {"object": (
                  {"apiVersion": "core.contrail.juniper.net/v1alpha1"}
                + {"kind": .[2] | type_case} 
                + {"metadata": (
                    {"uid": .[3]}
                  )}
                + {"spec": .[4] | spec_data}
                + {"status": .[4] | status_data}
                )}
            end
        )
];

# Convert etcd database state document into a list of Kubernetes objects.
def bulk_etcd_to_k8s:
{ 
  "items": 
  [
    .[]
        | { "apiVersion": "core.contrail.juniper.net/v1alpha1" }
        + { "kind": .type | type_case }
        + { "metadata": {
              "annotations": {
                "core.contrail.juniper.net/description": .id_perms.description,
                "core.contrail.juniper.net/display-name": .display_name
              },
              "creationTimestamp": .id_perms.created,
              "generation": 1,
              "name": .fq_name[-1],
              "resourceVersion": 1,
              "uid": .uuid
            }
          }
        + { "spec": . | spec_data }
        + { "status": {
                "fqName": .fq_name,
                "state": "Success"
            }
          }
];
