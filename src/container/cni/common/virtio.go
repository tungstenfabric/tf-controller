// vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
//
// Copyright (c) 2017 Juniper Networks, Inc. All rights reserved.
//

/****************************************************************************
 * File responsible to create and configure DPDK interfaces
 ****************************************************************************/
package cniIntf

import (
    "os"
    "io/ioutil"

    log "../logging"
)

// Definition for veth interface
type Virtio struct {
    CniIntf
    VhostIfName string
    SockName string
    SockDir string
}

func checkConfFileOrDirExists(fname string) error {
    if _, err := os.Stat(fname); err != nil {
        log.Errorf("File/Dir - %s does not exist. Error - %+v", fname, err)
        return err
    }
    return nil
}

// Delete Virtio interface configuration file
// Conffile is present under shared DIR mounted between host and pod
func (intf Virtio) Delete() error {
    log.Infof("Deleting Virtio interface %+v config", intf)
    sockDir := intf.GetSockDir();
    virtioIntfConfFile := sockDir + intf.SockName + ".conf"

    fileCheckErr := checkConfFileOrDirExists(virtioIntfConfFile)
    if fileCheckErr == nil{
        log.Infof("Deleting virtioIntfConfFile - %s", virtioIntfConfFile)
        fileErr := os.Remove(virtioIntfConfFile)
        if fileErr != nil {
            log.Errorf("Deleting configuration failed for interface %+v,"+
                       " virtioIntfConfFile %s", intf, virtioIntfConfFile)
            return fileErr
        }
    }

    dirCheckErr := checkConfFileOrDirExists(sockDir)
    if dirCheckErr == nil{
        log.Infof("Deleting sockDir - %s", sockDir)
        dirErr := os.RemoveAll(sockDir)
        if dirErr != nil {
            log.Errorf("Error Unable to Delete SockDir for interface %+v,"+
                        " sockDir %s", intf, sockDir)
            return dirErr
        }
    }

    log.Infof("Deleted configuration file for Virtio interface, filename %s",
                                                        virtioIntfConfFile)
    return nil
}

// Create Virtio interface configuration file.
// Conffile will be created under shared DIR mounted between host and pod
func (intf Virtio) Create() error {
    log.Infof("Creating Virtio interface %+v config", intf)
    sockDir := intf.GetSockDir();
    virtioIntfConfFile := sockDir + intf.SockName + ".conf"

    //Create Dir with vm_uuid if not present
    dirCheckErr := checkConfFileOrDirExists(sockDir)
    if dirCheckErr != nil{
        dirErr := os.Mkdir(sockDir, 0777)
        if dirErr != nil {
            log.Errorf("Error creating socket dir %s - %+v", sockDir, dirErr)
            return dirErr
        }
    }

    fileCheckErr := checkConfFileOrDirExists(virtioIntfConfFile)
    if fileCheckErr == nil {
        log.Errorf("Error creating Virtio Config file,"+
               " virtioIntfConfFile %s already present", virtioIntfConfFile)
        //File already present, don't overwrite, this could be double add
        return fileCheckErr
    }

    //Create interface conf filename as socket filename with .conf extention
    err := ioutil.WriteFile(virtioIntfConfFile, []byte(" "), 0600)
    if err != nil {
        log.Errorf("Error creating virtio configuration file, Write failed")
        return err
    }

    log.Infof("Created configuration file for Virtio interface, filename %s",
                                                         virtioIntfConfFile)
    return nil
}

func (intf Virtio) GetHostIfName() string {
    return intf.VhostIfName
}

func (intf Virtio) GetSockName() string {
    return intf.SockName
}

func (intf Virtio) GetSockDir() string {
    return (intf.SockDir + intf.containerUuid +"/")
}

func (intf Virtio) Log() {
    log.Infof("%+v", intf)
}

// Create SockName for vhost control channel. Name is based on container-id
func buildSockName(ifname string, ContainerId string) string {
    return ContainerId[:12]+"-"+ifname
}

// Create VhostIfName for vifName in vrouter
func buildVhostIfName(ifname string, ContainerId string) string {
    return "vhost" + ifname + "-" + ContainerId[:12]
}

func InitVirtio(containerIfName, containerId, containerUuid,
    containerNamespace string, mtu int) Virtio {
    intf := Virtio{
        CniIntf: CniIntf{
            containerId:        containerId,
            containerUuid:      containerUuid,
            containerIfName:    containerIfName,
            containerNamespace: containerNamespace,
            mtu:                mtu,
        },
        VhostIfName: "",
        SockName: "",
        SockDir: "",
    }

    intf.VhostIfName = buildVhostIfName(intf.containerIfName, intf.containerId)
    intf.SockName = buildSockName(intf.containerIfName, intf.containerId)
    //Init with base SockDir
    intf.SockDir = "/var/run/vrouter/"

    log.Infof("Initialized Virtio interface %+v", intf)
    return intf
}
