#!/usr/bin/env python3
#
# Copyright (c) 2020 Juniper Networks, Inc. All rights reserved.
#
#
#
# USAGE:
#
# Floating IP Deleting Tool
# ------------------------
#
# A tool to delete unassigned Floating IPS.
# Also can delete FIPs with error in VMI ref.
#
# usage: delete_fips.py [-h] [--list] [--delete-unassigned-fips] [--delete-error-fips] host
#
# positional arguments:
#   host                  host ip to connect to.
#
# optional arguments:
#   -h, --help            show this help message and exit
#   --list                list unassigned/error FIPs, no deletions made.
#   --delete-unassigned-fips
#                         perform unassigned FIP deletion operation.
#   --delete-error-fips   delete FIPs with error in VMI ref.
#
#
import sys
import argparse
import pprint

from vnc_api import vnc_api


def ip_to_num(ip):
    """
    Convert an IP string to a number value.
    :param ip: IP string to convert
    :return: A number representation of the IP address
    """
    s = ip[0].split(".")
    return int(s[0]) << 24 | int(s[1]) << 16 | int(s[2]) << 8 | int(s[3])


def find_missing_vmi_refs(api_server_host, more_info=False):
    """
    Gets a list of all floating IPs and organized them between good, unassigned,
    to_error, and unknown_exception lists.
    :param api_server_host: the host IP address to connect to.
    :param more_info: Will print additional information on the IPs.
    :return:  The set of floating IPs organized in types.
    """
    vnc_lib = vnc_api.VncApi(api_server_host=api_server_host)
    fip_set = {
        "good": [],  # list of properly assigned floating ips
        "unassigned": [],  # list of floating ips with unassigned MappedFixed IP Address
        "to_error": [],  # list of floating ips  where vmi_ref has 'to' field set to "['ERROR']
        "unknown_exception": [],  # keeps track of any unlikely exceptions while searching ips
    }
    res = vnc_lib.floating_ips_list(detail="true")
    for fip in res:
        try:
            ip_printed = False
            for vmi_ref in fip.virtual_machine_interface_refs:
                if vmi_ref["to"][0] == "ERROR":
                    if more_info:
                        print(
                            "FIP '{}' Invalid VMI reference ('to' == ['ERROR'], parent_type '{}'".format(
                                fip.floating_ip_address, fip.parent_types
                            )
                        )
                        print("PARENT TYPE to_error: {}".format(fip.parent_types))
                    fip_set["to_error"].append((fip.floating_ip_address, fip.uuid))
                else:
                    if not ip_printed:
                        if more_info:
                            print(
                                "FIP '{} - Valid VMI REF: {},parent_type '{}'".format(
                                    fip.floating_ip_address,
                                    fip.virtual_machine_interface_refs,
                                    fip.parent_types,
                                )
                            )
                        ip_printed = True
                    fip_set["good"].append((fip.floating_ip_address, fip.uuid))
        except AttributeError as exc:
            if more_info:
                print(
                    "FIP '{}' No VMI reference present (unassigned FIP?), parent_type '{}'".format(
                        fip.floating_ip_address, fip.parent_types
                    )
                )
            fip_set["unassigned"].append((fip.floating_ip_address, fip.uuid))
        except Exception as exc:
            if more_info:
                print(
                    "FIP '{}' Exception thrown when examining Floating IP:  {}".format(
                        fip.floating_ip_address, str(exc)
                    )
                )
            fip_set["unknown_exception"].append(fip.floating_ip_address)
    return fip_set


def delete_floating_ip(vnc_lib, uuid):
    """
    Delete a particular floating IP.
    :param vnc_lib: The vnc_lib object to use.
    :param uuid: The uuid of the floating IP to delete.
    :return: "success" or the str(exc) if exception thrown
    """
    try:
        # TODO: [uncommment next line to perform real delete]
        vnc_lib.floating_ip_delete(id=uuid)
        return "success"
    except Exception as exc:
        # return the exception error string
        return str(exc)


def print_fip_set(fip_set):
    """
    Print the list of floating IPs in the whole set
    :param fip_set: The set of floating IP lists
    :return: None
    """
    print("\n\nRESULTS:\n")
    for key, ips in fip_set.items():
        if key != "unknown_exception" or len(fip_set[key]) > 0:
            print("\n\nIP LIST: {}".format(key))
            pprint.pprint(sorted(fip_set[key], key=ip_to_num))


def delete_fip_list(host, fip_list):
    """
    Delete the list of floating IPs.
    :param host: The API server IP address
    :param fip_list: The list of floating IPs (ip,uuid) to delete
    :return: None
    """
    vnc_lib = vnc_api.VncApi(api_server_host=host)
    for entry in fip_list:
        fip, fip_uuid = entry
        result = delete_floating_ip(vnc_lib, fip_uuid)
        if result == "success":
            print("DELETED: {}".format(fip))
        else:
            print("FAILED TO DELETE: {}, ERROR: ".format(fip, result))


if __name__ == "__main__":
    print("")
    parser = argparse.ArgumentParser()
    parser.add_argument("host", help="host ip to connect to.", type=str)
    parser.add_argument(
        "--list",
        help="list unassigned/error FIPs, no deletions made.",
        action="store_true",
    )
    parser.add_argument(
        "--delete-unassigned-fips",
        help="perform unassigned FIP deletion operation.",
        action="store_true",
    )
    parser.add_argument(
        "--delete-error-fips",
        help="delete FIPs with error in VMI ref.",
        action="store_true",
    )
    args = parser.parse_args()

    # make sure at least one optional argument is selected
    if not (args.list or args.delete_unassigned_fips or args.delete_error_fips):
        print("Floating IP Deleting Tool")
        print("-------------------------")
        print(
            "\nA tool to delete unassigned Floating IPS.\nAlso can delete FIPs with error to == ['ERROR'] in VMI ref.\n"
        )
        print(parser.print_help())
        sys.exit()

    # will only do list if selected, other options specified are ignored
    if args.list:
        fip_set = find_missing_vmi_refs(args.host)
        print_fip_set(fip_set)
    else:
        # get list of fips
        fip_set = find_missing_vmi_refs(args.host)
        # delete all unassigned FIPs
        if args.delete_unassigned_fips:
            delete_fip_list(args.host, fip_set["unassigned"])
            print("Deleted unassigned FIPs")
        # delete all ERROR FIPs
        if args.delete_error_fips:
            delete_fip_list(args.host, fip_set["to_error"])
            print("Deleted error FIPs")
