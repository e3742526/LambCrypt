#!/usr/bin/env python3
# Modified for LambCrypt by the LambCrypt contributors. Changes from VeraCrypt are in the git history; see UPSTREAM.md.
"""Unit checks for macOS discovery and FSKit attach and teardown without mounts.

Compiles the production plist helpers and batch-refresh methods with a fake
inventory provider, so tests can supply incomplete inventories safely. Optional
--platform-archive runs the real bounded process runner from a matching build.
"""
import argparse
from pathlib import Path
import plistlib
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform-archive", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="lambcrypt-fskit.unit-", dir="/private/tmp") as temporary:
        work = Path(temporary)
        image = work / ".veracrypt_aux_mnt-test" / "volume.dmg"
        image.parent.mkdir()
        image.touch()
        alias = work / "path-alias"
        alias.symlink_to(work, target_is_directory=True)
        exact = dict(**{"image-path": str(image.resolve()), "system-entities": [{"dev-entry": "/dev/disk42", "mount-point": "/Volumes/unit"}]})
        alias_image = dict(exact, **{"image-path": str(alias / image.relative_to(work))})
        unknown_alias = dict(exact, **{"image-path": str(work / "missing" / image.parent.name / image.name)})
        second_device = {"system-entities": [{"dev-entry": "/dev/disk43"}]}
        exact_conflict = dict(exact, **second_device)
        alias_conflict = dict(alias_image, **second_device)
        cases = {
            "exact": {"images": [exact]},
            "reattached": {"images": [exact_conflict]},
            "same_attachment": {"images": [exact, alias_image]},
            "conflicting_exact": {"images": [exact, exact_conflict]},
            "conflicting_alias": {"images": [exact, alias_conflict]},
            "conflicting_alias_first": {"images": [alias_conflict, exact]},
            "conflicting_aliases": {"images": [alias_image, alias_conflict]},
            "conflicting_mount_points": {"images": [exact, dict(exact, **{"system-entities": [
                {"dev-entry": "/dev/disk42", "mount-point": "/Volumes/another"}]})]},
            "alias": {"images": [alias_image]},
            "absent": {"images": []},
            "unrelated": {"images": [dict(exact, **{"image-path": "/offline/unrelated.dmg"})]},
            "retained_after_auxiliary_loss": {"images": [
                dict(exact, **{"image-path": str(work / "removed-auxiliary" / "volume.dmg")})]},
            "exact_after_unknown": {"images": [unknown_alias, {}, exact]},
            "exact_before_unknown": {"images": [exact, {}, unknown_alias]},
            "unknown_alias": {"images": [unknown_alias]},
            "unknown_record": {"images": [{}]},
            "bad_entities": {"images": [{"image-path": str(image.resolve())}]},
            "non_disk_entity": {"images": [dict(exact, **{"system-entities": [
                {"dev-entry": "/dev/unavailable", "mount-point": "/Volumes/unit"}]})]},
        }
        for name, contents in cases.items():
            (work / name).write_bytes(plistlib.dumps(contents))
        (work / "attach").write_bytes(plistlib.dumps({"system-entities": exact["system-entities"]}))
        entities = [{"dev-entry": "/dev/disk42"}]
        (work / "attach-raw").write_bytes(plistlib.dumps({"system-entities": entities}))
        (work / "raw-inventory").write_bytes(plistlib.dumps({"images": [dict(exact, **{"system-entities": entities})]}))
        entities = entities + [{"dev-entry": "/dev/disk42s1"}]
        (work / "attach-partitioned").write_bytes(plistlib.dumps({"system-entities": entities}))
        for variant, sectors, cluster, fat_sectors in ((12, 2048, 1, 6), (16, 65536, 2, 128), (32, 196608, 1, 1536)):
            boot = bytearray(512)
            boot[:3] = b"\xeb\x3c\x90"
            boot[510:] = b"\x55\xaa"
            struct.pack_into("<HBHBHHBH", boot, 11, 512, cluster, 32 if variant == 32 else 1,
                             2, 0 if variant == 32 else 512, sectors if sectors < 65536 else 0, 0xf8,
                             0 if variant == 32 else fat_sectors)
            if sectors >= 65536:
                struct.pack_into("<I", boot, 32, sectors)
            if variant == 32:
                struct.pack_into("<IHHI", boot, 36, fat_sectors, 0, 0, 2)
            (work / f"fat{variant}").write_bytes(boot)
        (work / "custom-mount").mkdir()
        (work / "broken").write_text("invalid plist")
        (work / "linked-container").hardlink_to(image)

        source = (ROOT / "src/Core/Unix/MacOSX/CoreMacOSX.cpp").read_text()
        helpers = source[source.index("\tclass CFHolder"):source.index("\tCoreMacOSX::CoreMacOSX ()")]
        attached_device_start = source.index("\tDevicePath FSKit::GetAttachedDiskImageDevice")
        attached_device = source[attached_device_start:source.index("\n#endif", attached_device_start)]
        dismount = source[source.index("\tshared_ptr <VolumeInfo> CoreMacOSX::DismountVolume"):
                          source.index("\tstatic void ClearDiskImageInfo")]
        refresh = source[source.index("\tstatic void ClearDiskImageInfo"):source.index("\t// Strict /dev/diskN")]
        attach = source[source.index("\tDevicePath CoreMacOSX::MountAuxVolumeImage"):
                        source.index("\tunique_ptr <CoreBase> Core (")]
        attach = "\n#define open OpenKernelMountMedia\n" + attach + "\n#undef open\n"
        device_name_check = source[source.index("\tstatic bool IsPlainDiskDevicePath"):
                                   source.index("\tstatic int64_t GetDiskMediaRegistryId")]
        unix_source = (ROOT / "src/Core/Unix/CoreUnix.cpp").read_text()
        reservation_start = unix_source.index("\tstatic void ReserveLocalMacVolume")
        mac_reservation = unix_source[reservation_start:unix_source.index("\n#endif", reservation_start)]
        attachment_start = unix_source.index("\t\tDevicePath mountedVirtualDevice;")
        attachment_setup = unix_source[attachment_start:unix_source.index("\n\t\ttry", attachment_start)]
        attachment_attempt_start = unix_source.index("\t\t\t\tcatch (NotApplicable&)", attachment_start)
        attachment_attempt = unix_source[attachment_attempt_start:
                                         unix_source.index("\n\t\t\t}", attachment_attempt_start)]
        observation_start = unix_source.index("\t\t\t// The attach result and the fresh inventory")
        observation = unix_source[observation_start:unix_source.index("\n#endif", observation_start)]
        mount_end = unix_source.index("\n\t}\n\n\tDevicePath CoreUnix::MountAuxVolumeImage")
        rollback_start = unix_source.rindex("\n\t\t\treturn mountedVolume;\n\t\t}", 0, mount_end)
        rollback = unix_source[rollback_start:mount_end].split("\n\t\t}", 1)[1]
        slot_start = unix_source.index("\tint CoreUnix::ReserveMountSlot")
        slot_selection = unix_source[slot_start:unix_source.index("\n\tint CoreUnix::ReserveMountVolume", slot_start)]
        slot_selection = slot_selection.rsplit("\n#endif", 1)[0]
        fskit_source = (ROOT / "src/Driver/FSKit/FSKitService.mm").read_text()
        media_handoff = fskit_source[fskit_source.index("\t\tvoid ObserveAttachedMedia"):
                                    fskit_source.index("\t\tint AcquireUnmountLock")]
        auxiliary_start = fskit_source.index("\n", fskit_source.index("workerStarted = true;"))
        auxiliary_end = fskit_source.index("\n\t\t\t\treturn identity.SerialInstanceNumber", auxiliary_start)
        auxiliary_mount = fskit_source[auxiliary_start:auxiliary_end]
        resource_path = fskit_source[fskit_source.index("\t\t\tstring ResourcePath"):
                                    fskit_source.index("\t\t\tstring ApplicationGroupDirectory")]
        mount_lifetime = fskit_source[fskit_source.index("\t\t\tbool TryLockFile"):
                                     fskit_source.index("\t\t\tuint64 FindLateMedia")]
        worker_start = fskit_source.index("\t\t\t\tstruct pollfd descriptors[]")
        worker_end = fskit_source.index("\n\t\t\t\ttry { volume.Close", worker_start)
        worker_loop = fskit_source[worker_start:worker_end].replace("std::chrono::steady_clock", "PublicationClock")
        slot_lock = fskit_source[fskit_source.index("\t\tint TryReserveSlot"):
                                 fskit_source.index("\t\tuint64 Mount")]
        unmount_lock = fskit_source[fskit_source.index("\t\tint AcquireUnmountLock"):
                                    fskit_source.index("\t\tvoid WaitForServiceExit")]
        main_frame = (ROOT / "src/Main/Forms/MainFrame.cpp").read_text()
        slot_view_start = main_frame.index("\tstatic map <VolumeSlotNumber, shared_ptr <VolumeInfo>> GetMountedVolumesBySlot")
        slot_view = main_frame[slot_view_start:main_frame.index("\tshared_ptr <VolumeInfo> MainFrame::GetSelectedVolume", slot_view_start)]
        open_start = main_frame.index("\tvoid MainFrame::OpenSelectedVolume")
        open_volume = main_frame[open_start:main_frame.index("\tvoid MainFrame::OrganizeFavorites", open_start)]
        event_start = main_frame.index("\tvoid MainFrame::OnUpdateVolumeList")
        volume_event = main_frame[event_start:main_frame.index("\tvoid MainFrame::OnVolumeDiscoveryCompleted", event_start)]
        retention_start = main_frame.index("\t\t\t\t\t// Retain the identity")
        snapshot_retention = main_frame[retention_start:main_frame.index("\t\t\t\t\tMountedVolumes.swap", retention_start)]
        idle_start = main_frame.index("\t\t\t\t// Inactivity auto-dismount")
        idle_timer = main_frame[idle_start:main_frame.index("\t\t\t\t// Screen saver auto-dismount", idle_start)]
        idle_timer = idle_timer.replace("VolumeSnapshot.IsFresh()", "VolumeSnapshot.IsFresh(TestNow)")
        idle_timer = idle_timer.replace("chrono::steady_clock::now()", "TestNow")
        frame_header = (ROOT / "src/Main/Forms/MainFrame.h").read_text()
        activity_start = frame_header.index("\t\tstruct VolumeActivityMapEntry")
        activity_types = frame_header[activity_start:frame_header.index("\t\tmap <int, FavoriteVolume>", activity_start)]
        activity_member = next(line for line in frame_header.splitlines() if line.endswith(" VolumeActivityMap;"))
        graphic_ui = (ROOT / "src/Main/GraphicUserInterface.cpp").read_text()
        auto_dismount_start = graphic_ui.index("\tVolumeInfoList GraphicUserInterface::GetVolumesForAutoDismount")
        auto_dismount = graphic_ui[auto_dismount_start:graphic_ui.index("\tvoid GraphicUserInterface::ReportUnconfirmedCleanup", auto_dismount_start)]
        volume_info = (ROOT / "src/Volume/VolumeInfo.h").read_text()
        identity_start = volume_info.index("\t\tbool IsSameMountInstance")
        mount_identity = volume_info[identity_start:volume_info.index("\n\t\t}", identity_start) + len("\n\t\t}")]
        prelude = r'''
#include "Platform/Finally.h"
#include "Main/VolumeSnapshot.h"
#include "Core/Unix/MacOSX/FatBootSector.h"
#include <CoreFoundation/CoreFoundation.h>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <algorithm>
#include <array>
#include <cerrno>
#include <chrono>
#include <tuple>
#include <cstdlib>
#include <fcntl.h>
#include <map>
#include <poll.h>
#include <sys/file.h>
#include <sys/mount.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
#include <vector>
#define throw_sys_sub_if(condition, subject) do { if (condition) throw std::runtime_error(subject); } while(false)
using namespace std;
using VeraCrypt::GetFatBootSectorType;
#undef SRC_POS
#define SRC_POS "test source"
#define VERSION_NUM 1
using uint8 = uint8_t;
using uint64 = uint64_t;
using VolumeSlotNumber = unsigned int;
using DevicePath = std::string;
static string UnavailableBlockDevice;
struct DirectoryPath : std::string {
    using std::string::string;
    DirectoryPath() {}
    DirectoryPath(const std::string &s) : std::string(s) {}
    bool IsEmpty() const { return empty(); }
    bool IsBlockDevice() const { return find("/dev/disk") == 0 && *this != UnavailableBlockDevice; }
    operator wstring() const { return wstring(begin(), end()); }
};
struct ParameterIncorrect : std::runtime_error { ParameterIncorrect(const std::string &s) : std::runtime_error(s) {} };
struct VolumeDiscoveryFailed : std::runtime_error {
    VolumeDiscoveryFailed(const std::string &, const std::wstring &reason)
        : std::runtime_error(std::string(reason.begin(), reason.end())) {}
};
struct ExternalException : std::runtime_error {
    ExternalException(const string &, const wstring &reason) : std::runtime_error(string(reason.begin(), reason.end())) {}
};
struct DismountServiceCleanupFailed {
    DismountServiceCleanupFailed(const string &, const wstring &reason) : Reason(reason) {}
    wstring Reason;
};
struct MountServiceCleanupFailed {
    MountServiceCleanupFailed(const string &, const wstring &reason) : Reason(reason) {}
    wstring Reason;
};
struct MountedVolumeInUse { explicit MountedVolumeInUse(const string &) {} };
struct VolumeAlreadyMounted { explicit VolumeAlreadyMounted(const string &) {} };
struct VolumeSlotUnavailable { explicit VolumeSlotUnavailable(const string &) {} };
struct TimeOut {};
struct SystemException {
    SystemException() = default;
    SystemException(const string &, const string &) {}
};
struct ExecutedProcessFailed {
    explicit ExecutedProcessFailed(string error, int exitCode = 1) : Error(error), ExitCode(exitCode) {}
    ExecutedProcessFailed(const char *, const string &, int exitCode, const string &error)
        : ExecutedProcessFailed(error, exitCode) {}
    const char *what() const { return "mount failed"; }
    string GetCommand() const { return "/sbin/mount"; }
    int GetExitCode() const { return ExitCode; }
    string GetErrorOutput() const { return Error; }
    string Error;
    int ExitCode;
};
struct StringConverter {
    static std::string Trim(std::string s) { size_t b=s.find_first_not_of(" \t\r\n"); if(b==std::string::npos)return ""; return s.substr(b,s.find_last_not_of(" \t\r\n")-b+1); }
    static std::wstring ToWide(const std::string &s) { return wstring(s.begin(), s.end()); }
    static std::wstring ToExceptionString(const std::exception &error) { return ToWide(error.what()); }
};
static std::string Inventory;
static std::string InventoryAfterDetach;
static bool ReadPostDetachInventory;
static int Queries;
static vector<pair<string, int>> Commands;
static vector<list<string>> DismountArguments;
static string TimeoutCommand;
static bool AttachTimedOutBeforeLaunch;
static bool AttachLostOutput;
static bool AttachInterrupted;
static int ImageDetachStatus;
static string ImageDetachError;
static int AuxiliaryUnmountFailures;
static int MountValidations, RefuseValidation;
static string DismountMountPoint;
static bool FlushFailure;
static bool EjectedReadOnly;
static int GlobalSyncCalls;
static string AuxiliaryFailure;
static vector<list<string>> AttachCommands;
static string AttachReply;
static int AttachOptionFailures;
static list<uint64> MediaReads;
static string KernelMountFailure;
static list<string> KernelMountArguments;
static string KernelMountDevice;
static int KernelMediaFd = -1;
static bool KernelMediaOpenDenied;
static bool ReportKernelMount, KernelMountReadOnly, KernelMountIsFSKit;

static int OpenMountParent(const string &mountPoint) {
    const auto parent = mountPoint.substr(0, mountPoint.rfind('/'));
    int fd = open(parent.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (fd < 0) throw runtime_error("fixture mount parent unavailable");
    return fd;
}

static void RequireUnmountLock(const string &mountPoint) {
    const int observer = OpenMountParent(mountPoint);
    finally_do_arg(int, observer, { close(finally_arg); });
    if (flock(observer, LOCK_SH | LOCK_NB) == 0 || errno != EWOULDBLOCK)
        throw runtime_error("FSKit teardown step ran without the exclusive lock");
}

static int OpenKernelMountMedia(const char *path, int flags) {
    if (string(path) != "/dev/rdisk42" || flags != (O_RDONLY | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC))
        throw runtime_error("unexpected raw media open");
    if (KernelMediaOpenDenied) { errno = EACCES; return -1; }
    return KernelMediaFd = open("/dev/null", flags);
}

struct Process {
    static string ExecuteBounded(const string &path, const list<string> &arguments, int deadline,
                                 bool &completionUnconfirmed) {
        completionUnconfirmed = false;
        if (AttachTimedOutBeforeLaunch) throw TimeOut{};
        try {
            string output = ExecuteBounded(path, arguments, deadline);
            if (AttachLostOutput) throw SystemException{};
            if (AttachInterrupted) throw ExecutedProcessFailed("interrupted with -noautofsck");
            return output;
        }
        catch (...) {
            completionUnconfirmed = path == TimeoutCommand || AttachLostOutput || AttachInterrupted;
            throw;
        }
    }
    static string ExecuteBounded(const string &path, const list<string> &arguments, int deadline) {
        if (arguments.front() == "info") {
            if (deadline != 2000) throw runtime_error("discovery deadline");
            if (!DismountMountPoint.empty()) RequireUnmountLock(DismountMountPoint);
            ++Queries;
            if (ReadPostDetachInventory) {
                ReadPostDetachInventory = false;
                return InventoryAfterDetach;
            }
            return Inventory;
        }
        Commands.emplace_back(path, deadline);
        if (path == "/sbin/umount" && deadline != 0) RequireUnmountLock(arguments.back());
        if (arguments.front() == "detach" && deadline != 0) RequireUnmountLock(DismountMountPoint);
        if (path == "/sbin/mount_msdos") {
            RequireUnmountLock(DismountMountPoint);
            if (KernelMediaFd < 0 || fcntl(KernelMediaFd, F_GETFD) < 0)
                throw runtime_error("raw media descriptor did not stay open through the kernel mount");
            KernelMountArguments = arguments;
            KernelMountDevice = *prev(arguments.end(), 2);
            if (!KernelMountFailure.empty()) throw ExecutedProcessFailed(KernelMountFailure);
        }
        if (arguments.front() == "detach" || path == "/sbin/umount")
            DismountArguments.push_back(arguments);
        if (path == TimeoutCommand) throw TimeOut{};
        if (path == "/sbin/mount" && !AuxiliaryFailure.empty()) throw ExecutedProcessFailed(AuxiliaryFailure);
        if (ImageDetachStatus && arguments.front() == "detach")
            throw ExecutedProcessFailed(ImageDetachError, ImageDetachStatus);
        if (path == "/sbin/umount" && AuxiliaryUnmountFailures > 0) {
            --AuxiliaryUnmountFailures;
            throw ExecutedProcessFailed("Resource busy");
        }
        if (arguments.front() == "detach" && deadline != 0) ReadPostDetachInventory = true;
        if (arguments.front() == "attach") {
            AttachCommands.push_back(arguments);
            if (AttachOptionFailures > 0) {
                --AttachOptionFailures;
                throw ExecutedProcessFailed("unrecognized option: -noautofsck");
            }
            return AttachReply;
        }
        return {};
    }
    static string Execute(const string &path, const list<string> &arguments) {
        return ExecuteBounded(path, arguments, 0);
    }
    static string Execute(const string &path, const list<string> &arguments, int) {
        return ExecuteBounded(path, arguments, 0);
    }
};
struct FuseService { static std::string GetVolumeImagePath() { return "/volume.dmg"; } };
namespace FSKit {
    static bool IsAuxiliaryMountPoint(const DirectoryPath &path) {
        return string(path).find("/private/tmp/lambcrypt-fskit.") == 0;
    }
    int AcquireUnmountLock(const DirectoryPath &);
    void UnmountAuxiliary(const DirectoryPath &, bool);
    DevicePath GetAttachedDiskImageDevice(const DirectoryPath &);
    bool IsDiskImageAbsentAfterAuxiliaryUnmount(const DirectoryPath &);
    static uint64 GetMediaIdentity(const DevicePath &) {
        if (MediaReads.empty()) return 42;
        const uint64 media = MediaReads.front();
        MediaReads.pop_front();
        return media;
    }
    static string GetKernelFatMountPoint(const string &aux) { return aux.substr(0, aux.rfind('/')) + "/volume"; }
    static void WaitForServiceExit(const DirectoryPath &mountPoint) {
        const int observer = OpenMountParent(mountPoint);
        finally_do_arg(int, observer, { close(finally_arg); });
        if (flock(observer, LOCK_SH | LOCK_NB) != 0)
            throw runtime_error("cleanup waited for the worker while retaining the unmount lock");
        Commands.emplace_back("wait", 0);
    }
}
namespace Thread { static void Sleep(int) {} }
namespace VolumeProtection { enum { None, HiddenVolumeReadOnly, ReadOnly }; }
struct MountOptions {
    bool NoFilesystem = false;
    shared_ptr<DirectoryPath> MountPoint, Path;
    int Protection = VolumeProtection::None;
    unsigned int SlotNumber = 2;
};
struct SystemLog {
    static void WriteException(const std::exception &) {}
    static void WriteError(const string &) {}
};
#define foreach(declaration, collection) for (declaration : collection)
struct Volume {
    string Path;
    array<uint8_t, 512> Boot{};
    bool ReadFailed = false;
    size_t GetSectorSize() const { return Boot.size(); }
    uint64_t GetSize() const { return 96ULL << 20; }
    void ReadSectors(std::vector<uint8_t> &buffer, uint64) {
        if (ReadFailed) throw runtime_error("boot sector read failed");
        copy(Boot.begin(), Boot.end(), buffer.begin());
    }
    int GetProtectionType() const { return VolumeProtection::ReadOnly; }
};
struct SecureBuffer : std::vector<uint8_t> {
    using vector::vector;
    size_t Size() const { return size(); }
    uint8_t *Ptr() { return data(); }
};
struct VolumeInfo {
    enum DiscoveryState { DiscoveryUnknown, ImageAttached, ImageAbsent, ControlUnavailable };
    DiscoveryState Discovery = DiscoveryUnknown;
    DirectoryPath AuxMountPoint, MountPoint;
    DevicePath VirtualDevice;
    int Protection = VolumeProtection::None;
    DirectoryPath Path;
    unsigned int ProgramVersion = 0, SlotNumber = 0;
    uint64 SerialInstanceNumber = 0;
    uint64 TotalDataRead = 0, TotalDataWritten = 0;
    void Set(const Volume &volume) { Path = volume.Path; }
    shared_ptr<VolumeInfo> Clone() const { return make_shared<VolumeInfo>(*this); }
''' + mount_identity + r'''
};
namespace FSKit {
    static shared_ptr<VolumeInfo> ReadVolumeInfo(const DirectoryPath &mountPoint) {
        auto result = make_shared<VolumeInfo>();
        result->AuxMountPoint = mountPoint;
        result->Protection = EjectedReadOnly ? VolumeProtection::ReadOnly : VolumeProtection::None;
        return result;
    }
    static void FlushVolume(const VolumeInfo &volume) {
        RequireUnmountLock(volume.AuxMountPoint);
        Commands.emplace_back("flush", 0);
        if (FlushFailure) throw runtime_error("worker flush failed");
    }
}
static void CountGlobalSync() { ++GlobalSyncCalls; }
using VolumeInfoList = std::list<std::shared_ptr<VolumeInfo>>;
struct MountedFilesystem { DirectoryPath MountPoint; string Type; uint32_t Flags, ExtendedFlags; };
using MountedFilesystemList = std::list<std::shared_ptr<MountedFilesystem>>;
class CoreMacOSX {
public:
    shared_ptr<VolumeInfo> DismountVolume(shared_ptr<VolumeInfo>, bool, bool);
    shared_ptr<VolumeInfo> ValidateMountedVolume(shared_ptr<VolumeInfo> volume) const {
        if (++MountValidations == RefuseValidation) throw ParameterIncorrect(SRC_POS);
        return volume;
    }
    void UpdateMountedVolumesInfo(VolumeInfoList &) const;
    void UpdateMountedVolumeInfo(std::shared_ptr<VolumeInfo>) const;
    void UpdateMountedVolumeInfo(std::shared_ptr<VolumeInfo>, const std::string &) const;
    MountedFilesystemList GetMountedFilesystems(const DevicePath &dev, const DirectoryPath &path = {}) const {
        if (!ReportKernelMount || dev.IsEmpty() || dev != KernelMountDevice) return {};
        auto mount = make_shared<MountedFilesystem>();
        mount->MountPoint = path;
        mount->Type = "msdos";
        mount->Flags = KernelMountReadOnly ? MNT_RDONLY : 0;
        mount->ExtendedFlags = KernelMountIsFSKit ? MNT_EXT_FSKIT : 0;
        return {mount};
    }
    void ValidateMountPoint(const DirectoryPath &) const {}
    string GetDefaultMountPointPrefix() const { return "/Volumes/Untitled"; }
    DevicePath MountAuxVolumeImage(const DirectoryPath &, const MountOptions &, Volume * = nullptr, bool = false) const;
};
'''
        # Production path types expose IsEmpty(); keep that interface in the mock.
        prelude = prelude.replace("using DevicePath = std::string;", "")
        prelude = prelude.replace("struct ParameterIncorrect", "using DevicePath = DirectoryPath;\nstruct ParameterIncorrect")
        rollback_fixture = r'''
static const string StartupAuxiliary = "/private/tmp/lambcrypt-fskit.unit/.veracrypt_aux_mnt";
static const string StartupContainer = "/disposable.hc";
static const uint64 StartupSerial = 42;
static bool RefuseRollback;
static bool UnconfirmedRollback;
static bool StartupChannelClosed;
static shared_ptr<VolumeInfo> RollbackTarget;
static vector<int> PendingAttachmentChannels;
static vector<int> LateAttachmentChannels;
static vector<int> AttachedMediaChannels;

namespace FSKit {
static void BeginDiskImageAttachment(int channel) { PendingAttachmentChannels.push_back(channel); }
static void ObserveLateAttachedMedia(int channel) { LateAttachmentChannels.push_back(channel); }
static void ObserveAttachedMedia(int channel, const DevicePath &) { AttachedMediaChannels.push_back(channel); }
}

static shared_ptr<VolumeInfo> GetMountedVolume(const DirectoryPath &) {
    auto replacement = make_shared<VolumeInfo>();
    replacement->Path = StartupContainer;
    replacement->AuxMountPoint = "/private/tmp/lambcrypt-fskit.replacement/.veracrypt_aux_mnt";
    replacement->SerialInstanceNumber = StartupSerial + 1;
    return replacement;
}

static void DismountVolume(shared_ptr<VolumeInfo> volume) {
    if (!StartupChannelClosed) throw runtime_error("rollback held the worker activation channel open");
    RollbackTarget = volume;
    if (UnconfirmedRollback) throw DismountServiceCleanupFailed(SRC_POS, L"detach remains unconfirmed");
    if (RefuseRollback) throw runtime_error("worker identity unavailable");
}

enum class StartupFailure { BeforeAttach, AttachTimeout, AfterAttach, AfterHandoff };
struct NotApplicable {};

static int CloseStartupChannel(int channel) {
    if (channel != 15 || StartupChannelClosed) throw runtime_error("wrong startup channel");
    StartupChannelClosed = true;
    return 0;
}
#define close CloseStartupChannel
static void SimulateStartupFailure(StartupFailure failure) {
    StartupChannelClosed = false;
    const string fuseMountPoint = StartupAuxiliary;
    const uint64 mountServiceSerialInstanceNumber = StartupSerial;
    int activationChannel = 15;
    auto volume = make_shared<Volume>();
    volume->Path = StartupContainer;
    MountOptions options;
    options.Path = make_shared<DirectoryPath>(StartupContainer);
    const bool useDefaultMountPoint = false;
    auto MountAuxVolumeImage = [failure](const DirectoryPath &, const MountOptions &, Volume *, bool) -> DevicePath {
        if (failure == StartupFailure::AttachTimeout)
            throw MountServiceCleanupFailed(SRC_POS, L"attach remains unconfirmed");
        return "/dev/disk42";
    };
''' + attachment_setup + r'''
    try {
        if (failure != StartupFailure::BeforeAttach) {
            try { throw NotApplicable(); }
''' + attachment_attempt + r'''
        }
        if (failure == StartupFailure::AfterHandoff) {
            auto mountedVolume = make_shared<VolumeInfo>();
            mountedVolume->Discovery = VolumeInfo::ImageAttached;
            mountedVolume->VirtualDevice = mountedVirtualDevice;
''' + observation + r'''
        }
        throw runtime_error("startup failed");
    }
''' + rollback + "\n}\n#undef close\n"
        observation_fixture = r'''
namespace MediaObservationTest {
static vector<pair<int, uint64>> Reports;
static vector<DevicePath> Lookups;
static uint64 IdentifiedMedia;
namespace FSKit {
static uint64 GetMediaIdentity(const DevicePath &device) {
    Lookups.push_back(device);
    return IdentifiedMedia;
}
static void SendMediaIdentity(int channel, uint64 identity) { Reports.emplace_back(channel, identity); }
''' + media_handoff + r'''
}
static void Observe(VolumeInfo::DiscoveryState discovery, const DevicePath &discovered, uint64 identity) {
    const int activationChannel = 15;
    const DevicePath mountedVirtualDevice = "/dev/disk42";
    bool needsMediaObservation = true;
    auto mountedVolume = make_shared<VolumeInfo>();
    mountedVolume->Discovery = discovery;
    mountedVolume->VirtualDevice = discovered;
    IdentifiedMedia = identity;
''' + observation + r'''
}
}
'''
        auxiliary_fixture = r'''
static bool AuxiliaryMounted, AuxiliaryInventoryError, AuxiliaryAbsentOnce;
static fsid_t AuxiliaryIdentity;
static ssize_t AuxiliaryWorkerReply;
static unsigned int AuxiliaryDirectoriesRemoved;
static unsigned int AuxiliaryWorkerCommits;
static unsigned int AuxiliaryWorkerAborts;
static int AuxiliaryUnlinkError = ENOENT;

static bool MountTableEntry(const string &, fsid_t &identity) {
    if (AuxiliaryInventoryError) throw SystemException{};
    if (AuxiliaryAbsentOnce) {
        AuxiliaryAbsentOnce = false;
        return false;
    }
    identity = AuxiliaryIdentity;
    return AuxiliaryMounted;
}
static void RemoveEmptyMountDirectory(const string &) { ++AuxiliaryDirectoriesRemoved; }
static int FakeShutdown(int, int) { ++AuxiliaryWorkerAborts; return 0; }
static ssize_t FakeReceive(int, void *, size_t, int) {
    if (AuxiliaryWorkerReply < 0) errno = EAGAIN;
    return AuxiliaryWorkerReply;
}
static int FakeUnlink(const char *) { errno = AuxiliaryUnlinkError; return -1; }
static ssize_t FakeWrite(int, const void *data, size_t size) {
    if (size == 1 && *static_cast<const char *>(data) == 1)
        ++AuxiliaryWorkerCommits;
    return size;
}

#define shutdown FakeShutdown
#define recv FakeReceive
#define unlink FakeUnlink
#define write FakeWrite
#define throw_sys_if(condition) do { if (condition) throw SystemException{}; } while(false)
static void SimulateAuxiliaryMount() {
    const auto volume = make_shared<Volume>();
    int activation[] = {-1, -1};
    int activationChannel = -1;
    const string mountPoint = StartupAuxiliary;
    const string resource = "/unused-resource";
    const string endpoint = resource + "/io";
''' + auxiliary_mount + "\n}\n" + r'''
#undef throw_sys_if
#undef write
#undef unlink
#undef recv
#undef shutdown
'''
        mount_guard_fixture = r'''
#define throw_sys_if(condition) do { if (condition) throw SystemException{}; } while(false)
namespace FSKit {
static string ReservationDirectory;
static string ApplicationGroupDirectory() { return ReservationDirectory; }
''' + resource_path + mount_lifetime + slot_lock + unmount_lock + r'''
}
''' + mac_reservation + r'''
#undef throw_sys_if
class CoreUnix {
public:
    VolumeSlotNumber OccupiedSlot = 0;
    VolumeSlotNumber GetFirstSlotNumber() const { return 1; }
    VolumeSlotNumber GetFirstFreeSlotNumber() const { return 1; } // Inventory from before contention.
    VolumeSlotNumber GetDefaultMountPointSlot(const DirectoryPath &) const { return 1; }
    bool IsSlotNumberValid(VolumeSlotNumber slot) const { return slot >= 1 && slot <= 3; }
    bool IsSlotNumberAvailable(VolumeSlotNumber slot) const { return slot != OccupiedSlot; }
    DirectoryPath SlotNumberToMountPoint(VolumeSlotNumber slot) const { return "/Volumes/Unit" + std::to_string(slot); }
    int ReserveMountSlot(MountOptions &) const;
};
''' + slot_selection
        publication_fixture = r'''
namespace WorkerPublicationTest {
static chrono::milliseconds Elapsed;
static int PublishAfter, UnavailableThrough, Probes, Requests, MountedChecks;
static int ExitChecks, UnconfirmedExitChecks;
static bool SentActivation, SentPending, SentHandoff, Cancel, InitiallyUnavailable, PendingAttach;
static int FaultsInjected, MediaChecks, PendingRecords, PendingRemovals;
static bool InjectPollFaults, RetryMedia, MediaHelperRunning;
static vector<int> ExitStatuses;
static bool HelperRunning;
static constexpr uint64 PendingDiskImageAttachment = UINT64_MAX;
struct PublicationClock {
    using time_point = chrono::steady_clock::time_point;
    static time_point now() { return time_point(Elapsed); }
};
static bool PublicationTableEntry(const string &, fsid_t &identity) {
    ++Probes;
    if (Probes <= UnavailableThrough) throw SystemException{};
    if (InitiallyUnavailable && Probes == 1) throw SystemException{};
    if (PublishAfter != 0 && Probes == 2) throw SystemException{};
    identity = {{42, 7}};
    return PublishAfter != 0 && Probes >= PublishAfter;
}
static bool IsServiceMountPresent(int, const string &, const fsid_t &identity) {
    if (identity.val[0] != 42 || identity.val[1] != 7) throw runtime_error("worker used the wrong filesystem identity");
    ++MountedChecks;
    return RetryMedia && MediaChecks < 2;
}
static int Poll(pollfd *descriptors, unsigned int, int timeout) {
    descriptors[0].revents = descriptors[1].revents = 0;
    if (!SentActivation) {
        SentActivation = true;
        descriptors[1].revents = POLLIN;
        return 1;
    }
    if (timeout != 200) throw runtime_error("worker stopped checking for late publication");
    if (Cancel && descriptors[1].fd != -1) throw runtime_error("worker kept polling the cancellation EOF");
    if (PendingAttach && !SentPending) {
        SentPending = true;
        descriptors[1].revents = POLLIN;
        return 1;
    }
    if ((PublishAfter == 0 || MountedChecks > 1) && descriptors[1].fd >= 0 && !SentHandoff) {
        SentHandoff = true;
        descriptors[1].revents = POLLIN;
        return 1;
    }
    if (InjectPollFaults && ExitChecks == 1 && FaultsInjected < 2) {
        if (++FaultsInjected == 1) {
            errno = EIO;
            return -1;
        }
        descriptors[0].revents = POLLERR;
        return 1;
    }
    Elapsed += chrono::milliseconds(timeout);
    if (Elapsed > chrono::seconds(35)) throw runtime_error("worker failed to exit after confirmed image absence");
    if (Requests == 0 || (Requests == 1 && HelperRunning && UnconfirmedExitChecks > 0)) {
        descriptors[0].revents = POLLIN;
        return 1;
    }
    return 0;
}
static ssize_t Read(int fd, void *bytes, size_t size) {
    if (fd == 17 || (RetryMedia && SentHandoff)) {
        if (size != sizeof(uint64)) throw runtime_error("wrong media report size");
        const uint64 report = fd == 17 && MediaChecks > 1 ? 123 : 0;
        memcpy(bytes, &report, size);
        return size;
    }
    if (Cancel || SentHandoff) return 0;
    if (SentPending) {
        if (size != sizeof(PendingDiskImageAttachment)) throw runtime_error("wrong attachment marker size");
        memcpy(bytes, &PendingDiskImageAttachment, size);
        return size;
    }
    *static_cast<char *>(bytes) = 1;
    return 1;
}
static int Accept(int, void *, void *) { return 15; }
static int Close(int) { return 0; }
static int Pipe(int *fds) { fds[0] = 17; fds[1] = 18; return 0; }
static void RecordPendingAttachment(int, const string &) { ++PendingRecords; }
static int UnlinkPendingRecord(int, const char *, int) { ++PendingRemovals; return 0; }
static void ServeRequest(int, uid_t, Volume &, VolumeInfo &, const array<uint8_t, 16> &) { ++Requests; }
static uint64 IORegistryEntryIDMatching(uint64 media) { return media; }
static bool LookupMedia(uint64, uint64 &) { throw runtime_error("worker watched unconfirmed media"); }
static void CleanupEjectedMount(const string &, const fsid_t &) { throw runtime_error("unexpected eject helper"); }
static uint64 FindLateMedia(const string &, const fsid_t &) { throw runtime_error("unexpected late attach helper"); }
static void SendMediaIdentity(int, uint64) { throw runtime_error("unexpected media report"); }
static bool IsDiskImageAbsentAfterAuxiliaryUnmount(const string &) {
    throw runtime_error("inventory must run in the helper, not the worker");
}
static pid_t Fork() {
    if (HelperRunning || (!Cancel && !SentHandoff))
        throw runtime_error("exit check overlapped another helper or the mounting caller");
    HelperRunning = true;
    MediaHelperRunning = RetryMedia && MediaChecks < 2;
    if (MediaHelperRunning) {
        ++MediaChecks;
        return 16;
    }
    ++ExitChecks;
    return 16;
}
static pid_t WaitForHelper(pid_t child, int *status, int) {
    if (!HelperRunning || child != 16) throw runtime_error("wrong helper");
    HelperRunning = false;
    if (MediaHelperRunning) {
        *status = 0;
        return child;
    }
    *status = (ExitStatuses.empty() ? int(ExitChecks <= UnconfirmedExitChecks) : ExitStatuses.at(ExitChecks - 1)) << 8;
    return child;
}

#define poll Poll
#define read Read
#define accept Accept
#define close Close
#define fork Fork
#define pipe Pipe
#define unlinkat UnlinkPendingRecord
#define waitpid WaitForHelper
#define MountTableEntry PublicationTableEntry
static void Simulate(int publishAfter, bool cancel = false, bool initiallyUnavailable = false,
                     int unavailableThrough = 0, int unconfirmedExitChecks = 0,
                     const vector<int> &pendingExitStatuses = {}, bool injectPollFaults = false,
                     bool retryMedia = false) {
    Elapsed = chrono::milliseconds(0);
    Probes = Requests = MountedChecks = 0;
    SentActivation = SentPending = SentHandoff = HelperRunning = false;
    ExitChecks = 0;
    FaultsInjected = MediaChecks = PendingRecords = PendingRemovals = 0;
    InjectPollFaults = injectPollFaults;
    RetryMedia = retryMedia;
    UnconfirmedExitChecks = unconfirmedExitChecks;
    ExitStatuses = pendingExitStatuses;
    PendingAttach = !ExitStatuses.empty();
    PublishAfter = publishAfter;
    UnavailableThrough = unavailableThrough;
    Cancel = cancel;
    InitiallyUnavailable = initiallyUnavailable;
    const int listener = 12, commit = 13, directory = 14;
    const int volumeReservation = -1, slotReservation = -1, volumeFd = -1;
    const string mountPoint = "/fixture";
    Volume volume;
    VolumeInfo info;
    const array<uint8_t, 16> identifier = {};
''' + worker_loop + r'''
}
#undef MountTableEntry
#undef waitpid
#undef fork
#undef pipe
#undef unlinkat
#undef close
#undef accept
#undef read
#undef poll
}
'''
        tests = r'''
static void Require(bool condition, const char *message) { if(!condition)throw std::runtime_error(message); }
static std::string Read(const std::string &path) { std::ifstream f(path); return std::string(std::istreambuf_iterator<char>(f), {}); }
static void CheckMediaObservation() {
    using namespace MediaObservationTest;
    Observe(VolumeInfo::ImageAttached, "/dev/disk42", 123);
    Observe(VolumeInfo::ImageAttached, "/dev/disk42", 0);
    Observe(VolumeInfo::ImageAttached, "/dev/disk73", 123);
    Observe(VolumeInfo::DiscoveryUnknown, {}, 123);
    Require(Lookups == vector<DevicePath>{"/dev/disk42", "/dev/disk42"},
            "media observation trusted an uncorroborated BSD device");
    Require(Reports == vector<pair<int, uint64>>{{15, 123}, {15, 0}, {15, 0}, {15, 0}},
            "an unconfirmed media identity or inventory skipped the bounded observation request");
}
static void CheckLateWorkerPublication() {
    using namespace WorkerPublicationTest;
    Simulate(3);
    Require(Probes == 3 && Requests == 1 && ExitChecks == 1,
            "worker exited before a late mount appeared or stopped responding during publication");
    Simulate(0);
    Require(MountedChecks == 0 && Elapsed == chrono::seconds(10), "a mount that never published did not expire");
    Simulate(1, true);
    Require(Probes == 1 && ExitChecks == 1,
            "worker stopped despite auxiliary publication racing cancellation");
    Simulate(0, true);
    Require(Probes == 1 && Elapsed == chrono::milliseconds(0), "confirmed cancellation entered the publication wait");
    Simulate(0, true, true);
    Require(MountedChecks == 0 && Requests == 1 && Elapsed == chrono::seconds(10),
            "unconfirmed cancellation did not bound its publication wait while serving requests");
    Simulate(3, true, true);
    Require(Probes == 3 && Requests == 1 && ExitChecks == 1,
            "worker failed to retain a mount published after an inconclusive cancellation");
    Simulate(54, false, false, 53);
    Require(Probes == 54 && Requests == 1 && ExitChecks == 1,
            "worker exited at the publication deadline without a usable mount table");
    Simulate(0, false, false, 53);
    Require(Probes == 54 && Requests == 1 && MountedChecks == 0 && Elapsed >= chrono::seconds(10),
            "worker did not release its resources when inventory recovered and confirmed absence");
    Simulate(3, false, false, 0, 2);
    Require(ExitChecks == 3 && Requests == 2 && Elapsed >= chrono::seconds(10),
            "worker failed to retain the attachment, serve requests and back off before retrying");
    Simulate(3, false, false, 0, 0, {0, 2, 1, 0});
    Require(ExitChecks == 4 && Requests >= 1 && Elapsed >= chrono::seconds(15)
            && PendingRecords == 1 && PendingRemovals == 1,
            "worker released a pending attach before its late image appeared and was released");
    Simulate(0, false, false, 0, 0, {0, 1, 0});
    Require(MountedChecks == 0 && ExitChecks == 3 && Elapsed >= chrono::seconds(20),
            "worker missed a late image when it never observed the auxiliary mount");
    Simulate(3, false, false, 0, 2, {}, true);
    Require(FaultsInjected == 2 && ExitChecks == 3 && Requests >= 1,
            "poll failure bypassed attachment verification");
    Simulate(3, false, false, 0, 0, {}, false, true);
    Require(MediaChecks == 2 && ExitChecks == 1,
            "inconclusive late media lookup stopped observation permanently");
}
static void CheckLocalMacReservation(const string &root, const string &image) {
    const int first = open(image.c_str(), O_RDONLY);
    const int second = open((root + "/linked-container").c_str(), O_RDWR);
    Require(first >= 0 && second >= 0, "could not open reservation fixtures");
    ReserveLocalMacVolume(first);
    int release[2];
    Require(pipe(release) == 0, "could not create reservation handoff pipe");
    const pid_t service = fork();
    Require(service >= 0, "could not fork reservation fixture");
    if (service == 0) {
        close(release[1]);
        char byte;
        while (read(release[0], &byte, 1) < 0 && errno == EINTR) {}
        _exit(0);
    }
    close(release[0]);
    close(first);
    bool refused = false;
    try { ReserveLocalMacVolume(second); }
    catch (const VolumeAlreadyMounted &) { refused = true; }
    close(release[1]);
    int status;
    pid_t reaped;
    do { reaped = waitpid(service, &status, 0); } while (reaped < 0 && errno == EINTR);
    Require(reaped == service && WIFEXITED(status) && refused,
            "service handoff dropped the read-only volume reservation or a hard link bypassed it");
    ReserveLocalMacVolume(second);
    close(second);
}
static void CheckBackingReservation(const string &root, const string &image) {
    const int original = open(image.c_str(), O_RDONLY | O_CLOEXEC);
    const int alias = open((root + "/linked-container").c_str(), O_RDONLY | O_CLOEXEC);
    const int distinct = open((root + "/exact").c_str(), O_RDONLY | O_CLOEXEC);
    finally_do_arg(int, original, { close(finally_arg); });
    finally_do_arg(int, alias, { close(finally_arg); });
    finally_do_arg(int, distinct, { close(finally_arg); });
    Require(original >= 0 && alias >= 0 && distinct >= 0, "could not open reservation fixtures");
    {
        const int reservation = FSKit::ReserveVolume(root, original);
        finally_do_arg(int, reservation, { close(finally_arg); });
        const int otherReservation = FSKit::ReserveVolume(root, distinct);
        finally_do_arg(int, otherReservation, { close(finally_arg); });
        bool busy = false;
        try { close(FSKit::ReserveVolume(root, alias)); }
        catch (const VolumeAlreadyMounted &) { busy = true; }
        Require(busy, "hard link acquired a second reservation for the same backing file");
    }
    const int reopened = FSKit::ReserveVolume(root, alias);
    close(reopened);
}
static void CheckSlotReservation(const string &root) {
    FSKit::ReservationDirectory = root;
    CoreUnix core;
    MountOptions explicitSlot;
    explicitSlot.SlotNumber = 1;
    explicitSlot.NoFilesystem = true;
    {
        const int held = core.ReserveMountSlot(explicitSlot);
        finally_do_arg(int, held, { close(finally_arg); });
        bool busy = false;
        try { close(core.ReserveMountSlot(explicitSlot)); }
        catch (const VolumeSlotUnavailable &) { busy = true; }
        Require(busy, "two callers reserved the same explicit slot");
        core.OccupiedSlot = 2;
        MountOptions automatic;
        automatic.SlotNumber = 0;
        const int next = core.ReserveMountSlot(automatic);
        finally_do_arg(int, next, { close(finally_arg); });
        Require(automatic.SlotNumber == 3 && *automatic.MountPoint == "/Volumes/Unit3",
                "automatic assignment did not skip locked and discovered slots");
    }
    close(core.ReserveMountSlot(explicitSlot));
}
static void CheckWorkerTeardown(const string &mountPoint) {
    const fsid_t original = {{42, 7}};
    const int worker = OpenMountParent(mountPoint);
    finally_do_arg(int, worker, { close(finally_arg); });
    {
        const int unmount = FSKit::AcquireUnmountLock(DirectoryPath(mountPoint));
        finally_do_arg(int, unmount, { close(finally_arg); });
        Require(!AuxiliaryMounted && FSKit::IsServiceMountPresent(worker, mountPoint, original),
                "worker exited while an unmount decision was pending");
        bool busy = false;
        try { close(FSKit::AcquireUnmountLock(DirectoryPath(mountPoint))); }
        catch (const MountedVolumeInUse &) { busy = true; }
        Require(busy, "two callers acquired the same unmount lock");
    }
    Require(!FSKit::IsServiceMountPresent(worker, mountPoint, original), "confirmed absence retained the worker");
    AuxiliaryMounted = AuxiliaryAbsentOnce = true;
    AuxiliaryIdentity = original;
    Require(FSKit::IsServiceMountPresent(worker, mountPoint, original), "worker failed to recheck transient absence");
    AuxiliaryIdentity.val[0]++;
    Require(!FSKit::IsServiceMountPresent(worker, mountPoint, original), "worker adopted a replacement mount");
    AuxiliaryMounted = false;
}
static void CheckExternalEjectCleanup(const string &root, const string &image) {
    const string mountPoint = image.substr(0, image.rfind('/'));
    DismountMountPoint = mountPoint;
    const fsid_t original = {{42, 7}};
    AuxiliaryMounted = true;
    AuxiliaryIdentity = original;
    Commands.clear();
    Inventory = Read(root + "/exact");
    FSKit::CleanupEjectedMount(mountPoint, original);
    Require(Commands.empty(), "eject cleanup attempted to unmount an attached disk image");
    Inventory = Read(root + "/unknown_record");
    bool unknown = false;
    try { FSKit::CleanupEjectedMount(mountPoint, original); }
    catch (const ParameterIncorrect &) { unknown = true; }
    Require(unknown && Commands.empty(), "incomplete inventory triggered automatic cleanup");
    Inventory = Read(root + "/absent");
    ++AuxiliaryIdentity.val[0];
    FSKit::CleanupEjectedMount(mountPoint, original);
    Require(Commands.empty(), "eject cleanup unmounted a replacement filesystem");
    AuxiliaryIdentity = original;
    {
        const int lock = FSKit::AcquireUnmountLock(mountPoint);
        finally_do_arg(int, lock, { close(finally_arg); });
        bool busy = false;
        try { FSKit::CleanupEjectedMount(mountPoint, original); }
        catch (const MountedVolumeInUse &) { busy = true; }
        Require(busy && Commands.empty(), "eject cleanup raced an explicit dismount");
    }
    FlushFailure = true;
    bool flushFailed = false;
    try { FSKit::CleanupEjectedMount(mountPoint, original); }
    catch (const runtime_error &error) { flushFailed = string(error.what()) == "worker flush failed"; }
    Require(flushFailed && Commands == vector<pair<string, int>>{{"flush", 0}},
            "failed external-eject flush unmounted the writable worker");
    FlushFailure = false;
    for (const bool readOnly : {false, true}) {
        EjectedReadOnly = readOnly;
        Commands.clear();
        FSKit::CleanupEjectedMount(mountPoint, original);
        vector<pair<string, int>> expected;
        if (!readOnly) expected.emplace_back("flush", 0);
        expected.emplace_back("/sbin/umount", 10000);
        Require(Commands == expected, "external eject did not sync a writable image before auxiliary unmount");
        Require(DismountArguments.back() == list<string>{"--", mountPoint}, "automatic cleanup forced an unmount");
    }
    AuxiliaryMounted = false;
}
static void CheckAttach(CoreMacOSX &core, const DirectoryPath &auxiliary) {
    MountOptions options;
    options.NoFilesystem = true;
    options.Protection = VolumeProtection::ReadOnly;
    auto hasOption = [](const list<string> &arguments, const string &option) {
        return find(arguments.begin(), arguments.end(), option) != arguments.end();
    };
    auto reset = []() { Commands.clear(); AttachCommands.clear(); };
    reset();
    Require(core.MountAuxVolumeImage(auxiliary, options) == "/dev/disk42", "attach did not return its device");
    Require(Commands == vector<pair<string, int>>{{"/usr/bin/hdiutil", 30000}}, "FSKit attach has no deadline");
    Require(hasOption(AttachCommands.front(), "-nomount") && hasOption(AttachCommands.front(), "-readonly"),
            "attach lost read-only or attach-only flags");

    for (const string failure : {"timeout", "output", "interrupted"}) {
        reset();
        TimeoutCommand = failure == "timeout" ? "/usr/bin/hdiutil" : "";
        AttachLostOutput = failure == "output";
        AttachInterrupted = failure == "interrupted";
        bool unconfirmed = false;
        try { core.MountAuxVolumeImage(auxiliary, options); }
        catch (const MountServiceCleanupFailed &e) {
            unconfirmed = e.Reason.find(L"macOS did not confirm disk image attach: " + wstring(auxiliary) + L"/volume.dmg") == 0;
        }
        Require(unconfirmed && Commands.size() == 1, "unconfirmed attach lost its cleanup state or retried");
    }
    TimeoutCommand.clear();
    AttachLostOutput = AttachInterrupted = false;

    reset();
    AttachTimedOutBeforeLaunch = true;
    bool notLaunched = false;
    try { core.MountAuxVolumeImage(auxiliary, options); }
    catch (const TimeOut &) { notLaunched = true; }
    AttachTimedOutBeforeLaunch = false;
    Require(notLaunched && Commands.empty(), "an attach that never started was treated as pending");

    reset();
    AttachOptionFailures = 1;
    Require(core.MountAuxVolumeImage(auxiliary, options) == "/dev/disk42", "compatibility retry lost a successful attach");
    Require(AttachCommands.size() == 2 && hasOption(AttachCommands.front(), "-noautofsck")
            && !hasOption(AttachCommands.back(), "-noautofsck"), "compatibility retry did not drop its unsupported option");

    reset();
    AttachOptionFailures = 2;
    bool failed = false;
    try { core.MountAuxVolumeImage(auxiliary, options); }
    catch (const ExecutedProcessFailed &) { failed = true; }
    Require(failed && AttachCommands.size() == 2, "repeated option error retried an attach again");
}
static void CheckKernelFat(CoreMacOSX &core, const DirectoryPath &auxiliary, const string &root) {
    Volume volume;
    MountOptions options;
    options.MountPoint = make_shared<DirectoryPath>(root + "/custom-mount");
    const auto load = [&](int type) {
        const auto boot = Read(root + "/fat" + to_string(type));
        copy(boot.begin(), boot.end(), volume.Boot.begin());
        Require(GetFatBootSectorType(volume.Boot.data(), volume.Boot.size(), volume.GetSize()) == type,
                "wrong FAT width from BIOS parameter block");
        Require(GetFatBootSectorType(volume.Boot.data(), 511, volume.GetSize()) == 0
                && GetFatBootSectorType(volume.Boot.data(), volume.Boot.size(), 512) == 0,
                "invalid FAT geometry selected the kernel driver");
    };
    const auto reset = [&] {
        Require(KernelMediaFd < 0 || fcntl(KernelMediaFd, F_GETFD) == -1,
                "raw media descriptor leaked from the kernel mount");
        KernelMediaFd = -1;
        KernelMediaOpenDenied = false;
        Commands.clear();
        AttachCommands.clear();
        MediaReads.clear();
        TimeoutCommand.clear();
        KernelMountFailure.clear();
        KernelMountArguments.clear();
        ReportKernelMount = true;
        KernelMountIsFSKit = false;
        KernelMountReadOnly = options.Protection == VolumeProtection::ReadOnly;
        Inventory = Read(root + "/raw-inventory");
        AttachReply = Read(root + "/attach-raw");
    };
    DismountMountPoint = auxiliary;
    for (const int type : {12, 16, 32}) {
        load(type);
        for (const bool readOnly : {false, true}) {
            options.Protection = readOnly ? VolumeProtection::ReadOnly : VolumeProtection::None;
            reset();
            Require(core.MountAuxVolumeImage(auxiliary, options, &volume, false) == "/dev/disk42",
                    "kernel mount lost its device");
            Require(Commands == vector<pair<string, int>>{{"/usr/bin/hdiutil", 30000}, {"/sbin/mount_msdos", 15000}}
                    && AttachCommands.front().end() != find(AttachCommands.front().begin(), AttachCommands.front().end(), "-nomount")
                    && KernelMountArguments == list<string>{"-o", readOnly ? "ro,nosuid,nodev" : "nosuid,nodev",
                        "/dev/disk42", *options.MountPoint}, "kernel FAT route lost its access or identity");
        }
    }
    reset();
    const auto defaultPath = FSKit::GetKernelFatMountPoint(auxiliary);
    core.MountAuxVolumeImage(auxiliary, options, &volume, true);
    Require(KernelMountArguments.back() == defaultPath && rmdir(defaultPath.c_str()) == 0,
            "default FAT mount was not placed in an owned mount directory");

    reset();
    options.NoFilesystem = true;
    volume.ReadFailed = true;
    core.MountAuxVolumeImage(auxiliary, options, &volume, false);
    Require(KernelMountArguments.empty(), "attach-only attempted a filesystem mount");
    options.NoFilesystem = false;

    reset();
    bool probeFailed = false;
    try { core.MountAuxVolumeImage(auxiliary, options, &volume, false); }
    catch (const runtime_error &error) { probeFailed = string(error.what()) == "boot sector read failed"; }
    Require(probeFailed && Commands.empty(), "a failed filesystem probe attached an image");
    volume.ReadFailed = false;

    DismountMountPoint.clear();
    for (const auto *signature : {"EXFAT   ", "HFSPLUS ", "UNKNOWN "}) {
        volume.Boot.fill(0);
        copy_n(signature, 8, volume.Boot.begin() + 3);
        reset();
        AttachReply = Read(root + "/attach");
        core.MountAuxVolumeImage(auxiliary, options, &volume, false);
        Require(KernelMountArguments.empty() && AttachCommands.front().end() !=
                find(AttachCommands.front().begin(), AttachCommands.front().end(), "required"),
                "non-FAT did not use system filesystem selection");
    }
    load(16);
    DismountMountPoint = auxiliary;
    reset();
    AttachReply = Read(root + "/attach-partitioned");
    bool partitioned = false;
    try { core.MountAuxVolumeImage(auxiliary, options, &volume, false); }
    catch (const ParameterIncorrect &) { partitioned = true; }
    Require(partitioned && KernelMountArguments.empty(), "ambiguous raw attachment reached the kernel driver");

    const auto unconfirmed = [&](bool ranKernel) {
        bool keptWorker = false;
        try { core.MountAuxVolumeImage(auxiliary, options, &volume, false); }
        catch (const MountServiceCleanupFailed &) { keptWorker = true; }
        Require(keptWorker && (!KernelMountArguments.empty() == ranKernel),
                "unconfirmed mount did not preserve its worker or attempted the wrong command");
    };
    reset();
    MediaReads = {42, 43};
    unconfirmed(false);
    reset();
    KernelMediaOpenDenied = true;
    bool missingDescriptor = false;
    try { core.MountAuxVolumeImage(auxiliary, options, &volume, false); }
    catch (const runtime_error &error) { missingDescriptor = string(error.what()) == "/dev/rdisk42"; }
    Require(missingDescriptor && KernelMountArguments.empty(), "a failed raw open reached the kernel driver");
    reset();
    MediaReads = {42, 42, 43};
    unconfirmed(false);
    reset();
    Inventory = Read(root + "/absent");
    unconfirmed(false);
    reset();
    TimeoutCommand = "/sbin/mount_msdos";
    unconfirmed(true);
    reset();
    MediaReads = {42, 42, 42, 43};
    unconfirmed(true);
    reset();
    KernelMountFailure = "mount rejected";
    bool rejected = false;
    try { core.MountAuxVolumeImage(auxiliary, options, &volume, false); }
    catch (const ExecutedProcessFailed &) { rejected = true; }
    Require(rejected, "ordinary mount rejection did not request startup rollback");
    for (const bool wrongDriver : {false, true}) {
        reset();
        KernelMountReadOnly = wrongDriver;
        KernelMountIsFSKit = wrongDriver;
        bool wrongMount = false;
        try { core.MountAuxVolumeImage(auxiliary, options, &volume, false); }
        catch (const ExternalException &) { wrongMount = true; }
        Require(wrongMount, "unexpected driver or access mode was treated as mounted");
    }
    reset();
    DismountMountPoint.clear();
}
static void CheckStartupRollback() {
    for (const auto failure : {StartupFailure::BeforeAttach, StartupFailure::AfterAttach}) {
        bool keptStartupError = false;
        try { SimulateStartupFailure(failure); }
        catch (const runtime_error &e) { keptStartupError = string(e.what()) == "startup failed"; }
        Require(keptStartupError && RollbackTarget && RollbackTarget->AuxMountPoint == StartupAuxiliary
                && RollbackTarget->SerialInstanceNumber == StartupSerial && RollbackTarget->SlotNumber == 2
                && RollbackTarget->Path == StartupContainer, "startup rollback used a replacement mount identity");
        Require(StartupChannelClosed, "confirmed rollback did not release the activation channel");
        Require(LateAttachmentChannels == (failure == StartupFailure::AfterAttach ? vector<int>{15} : vector<int>{}),
                "rollback handed off the wrong attachment state");
    }

    RefuseRollback = true;
    for (const auto failure : {StartupFailure::BeforeAttach, StartupFailure::AfterAttach, StartupFailure::AfterHandoff}) {
        LateAttachmentChannels.clear();
        AttachedMediaChannels.clear();
        bool warnedOfFailure = false;
        try { SimulateStartupFailure(failure); }
        catch (const MountServiceCleanupFailed &e) {
            warnedOfFailure = e.Reason == StringConverter::ToWide(StartupAuxiliary) + L"\nworker identity unavailable";
        }
        Require(warnedOfFailure, "startup rollback failure was hidden");
        if (failure == StartupFailure::AfterAttach)
            Require(LateAttachmentChannels == vector<int>{15}, "failed rollback lost late attachment observation");
        else
            Require(LateAttachmentChannels.empty(), "rollback requested an unnecessary late attach probe");
        if (failure == StartupFailure::AfterHandoff)
            Require(AttachedMediaChannels == vector<int>{15}, "rollback repeated the direct media handoff");
    }

    LateAttachmentChannels.clear();
    UnconfirmedRollback = true;
    bool keptRollbackWarning = false;
    try { SimulateStartupFailure(StartupFailure::AfterAttach); }
    catch (const DismountServiceCleanupFailed &e) { keptRollbackWarning = e.Reason == L"detach remains unconfirmed"; }
    Require(keptRollbackWarning && LateAttachmentChannels == vector<int>{15},
            "unconfirmed detach lost its warning or the media observation handoff");
    UnconfirmedRollback = false;

    LateAttachmentChannels.clear();
    RollbackTarget.reset();
    PendingAttachmentChannels.clear();
    bool keptAttachWarning = false;
    try { SimulateStartupFailure(StartupFailure::AttachTimeout); }
    catch (const MountServiceCleanupFailed &e) { keptAttachWarning = e.Reason == L"attach remains unconfirmed"; }
    Require(keptAttachWarning && !RollbackTarget && PendingAttachmentChannels == vector<int>{15}
            && LateAttachmentChannels.empty(),
            "unconfirmed attach did not preserve its worker for late observation");
}
static void CheckAuxiliaryMountStartup() {
    Commands.clear();
    SimulateAuxiliaryMount();
    Require(Commands == vector<pair<string, int>>{{"/sbin/mount", 30000}},
            "FSKit auxiliary mount child was not bounded");
    Require(AuxiliaryWorkerCommits == 1, "successful auxiliary mount did not commit its worker");
    AuxiliaryWorkerCommits = 0;

    auto requireTimeout = []() {
        bool reported = false;
        try { SimulateAuxiliaryMount(); }
        catch (const MountServiceCleanupFailed &e) {
            reported = e.Reason.find(L"did not confirm auxiliary mount") != wstring::npos
                && e.Reason.find(L"Recheck the mounted volume list after 10 seconds") != wstring::npos;
        }
        Require(reported && AuxiliaryDirectoriesRemoved == 0, "unconfirmed mount triggered local cleanup");
    };
    TimeoutCommand = "/sbin/mount";
    requireTimeout();
    Require(AuxiliaryWorkerCommits == 1, "mount timeout canceled its worker before a late mount could appear");
    AuxiliaryMounted = true;
    requireTimeout();
    Require(AuxiliaryWorkerCommits == 2, "timeout abandoned a mounted FSKit worker");
    AuxiliaryInventoryError = true;
    requireTimeout();
    Require(AuxiliaryWorkerCommits == 3, "unavailable mount table canceled its worker after a timeout");
    AuxiliaryMounted = AuxiliaryInventoryError = false;
    TimeoutCommand.clear();

    AuxiliaryFailure = "LambCrypt is disabled!";
    bool explainedDisabled = false;
    try { SimulateAuxiliaryMount(); }
    catch (const ExecutedProcessFailed &e) {
        explainedDisabled = e.GetErrorOutput().find("enable LambCrypt FSKit") != string::npos;
    }
    Require(explainedDisabled && AuxiliaryDirectoriesRemoved == 1, "confirmed cleanup lost its activation help");

    auto requireUnconfirmed = []() {
        bool reported = false;
        try { SimulateAuxiliaryMount(); }
        catch (const MountServiceCleanupFailed &e) {
            reported = e.Reason.find(L"LambCrypt is disabled!") != wstring::npos;
        }
        Require(reported && AuxiliaryDirectoriesRemoved == 1, "unconfirmed startup cleanup lost its warning");
    };
    AuxiliaryWorkerReply = -1;
    requireUnconfirmed();
    AuxiliaryWorkerReply = 0;
    const auto commits = AuxiliaryWorkerCommits;
    const auto aborts = AuxiliaryWorkerAborts;
    AuxiliaryMounted = true;
    requireUnconfirmed();
    Require(AuxiliaryWorkerCommits == commits + 1 && AuxiliaryWorkerAborts == aborts,
            "a failed helper canceled the worker for an already-published auxiliary mount");
    AuxiliaryMounted = false;
    AuxiliaryInventoryError = true;
    requireUnconfirmed();
    Require(AuxiliaryWorkerCommits == commits + 2 && AuxiliaryWorkerAborts == aborts,
            "a failed helper canceled the worker while the mount table was unavailable");
    AuxiliaryInventoryError = false;
    AuxiliaryUnlinkError = EACCES;
    requireUnconfirmed();
    AuxiliaryUnlinkError = ENOENT;
    AuxiliaryFailure.clear();
}
static void CheckDismount(CoreMacOSX &core, const string &image, const string &root) {
    auto mounted = make_shared<VolumeInfo>();
    mounted->AuxMountPoint = image.substr(0, image.rfind('/'));
    mounted->Protection = VolumeProtection::ReadOnly;
    DismountMountPoint = mounted->AuxMountPoint;
    const string exactInventory = Inventory;
    InventoryAfterDetach = Read(root + "/absent");
    for (const auto *record : {"conflicting_exact", "conflicting_alias", "conflicting_alias_first",
                              "conflicting_aliases", "conflicting_mount_points"}) {
        Inventory = Read(root + "/" + record);
        for (bool force : {false, true}) {
            Commands.clear();
            const int queries = Queries;
            bool refused = false;
            try { core.DismountVolume(mounted, force, false); }
            catch (const VolumeDiscoveryFailed &error) {
                refused = string(error.what()).find("conflicting attachments") != string::npos;
            }
            Require(refused && Queries == queries + 1 && Commands.empty(),
                    "ambiguous attachment reached detach or backing cleanup");
        }
    }
    Inventory = exactInventory;
    for (const auto *record : {"exact_after_unknown", "exact_before_unknown"}) {
        Inventory = Read(root + "/" + record);
        for (bool force : {false, true}) {
            Commands.clear();
            bool refused = false;
            try { core.DismountVolume(mounted, force, false); }
            catch (const DismountServiceCleanupFailed &) { refused = true; }
            Require(refused && Commands.empty(), "partial inventory authorized detach of a known match");
        }
    }
    Inventory = exactInventory;
    for (const auto *record : {"exact", "reattached", "unknown_record", "conflicting_exact"}) {
        InventoryAfterDetach = Read(root + "/" + record);
        for (bool force : {false, true}) {
            Commands.clear();
            const int queries = Queries;
            bool unconfirmed = false;
            try { core.DismountVolume(mounted, force, false); }
            catch (const DismountServiceCleanupFailed &error) {
                unconfirmed = error.Reason.find(L"disk image detach") != wstring::npos;
            }
            Require(unconfirmed && Queries == queries + 3
                    && Commands == vector<pair<string, int>>{{"/usr/bin/hdiutil", 30000}},
                    "successful detach with an attached or unknown image reached backing cleanup");
        }
    }
    InventoryAfterDetach = Read(root + "/absent");
    auto requireUnconfirmedDevice = [&](bool force) {
        Commands.clear();
        bool reported = false;
        try { core.DismountVolume(mounted, force, false); }
        catch (const DismountServiceCleanupFailed &error) {
            reported = error.Reason.find(L"block device") != wstring::npos;
        }
        Require(reported && Commands.empty(), "unresolved attached device reached FSKit unmount");
    };
    Inventory = Read(root + "/non_disk_entity");
    requireUnconfirmedDevice(false);
    requireUnconfirmedDevice(true);
    Inventory = exactInventory;
    MediaReads = {42, 43};
    Commands.clear();
    bool reused = false;
    try { core.DismountVolume(mounted, false, false); }
    catch (const DismountServiceCleanupFailed &error) { reused = error.Reason.find(L"identity") != wstring::npos; }
    Require(reused && Commands.empty(), "disk-number reuse reached detach");
    UnavailableBlockDevice = "/dev/disk42";
    requireUnconfirmedDevice(false);
    requireUnconfirmedDevice(true);
    UnavailableBlockDevice.clear();
    Inventory = Read(root + "/absent");
    Commands.clear();
    core.DismountVolume(mounted, false, false);
    Require(Commands == vector<pair<string, int>>{{"/sbin/umount", 10000}, {"wait", 0}},
            "confirmed image absence did not permit auxiliary cleanup");
    Inventory = exactInventory;
    auto attempt = [&](const char *blocked, const wchar_t *detail, size_t expectedCommands) {
        TimeoutCommand = blocked;
        Commands.clear();
        bool failed = false;
        try { core.DismountVolume(mounted, false, false); }
        catch (const DismountServiceCleanupFailed &e) { failed = e.Reason.find(detail) != wstring::npos; }
        Require(failed && Commands.size() == expectedCommands, "timeout ran later teardown steps or lost the failed step");
        Require(Commands[0] == make_pair(string("/usr/bin/hdiutil"), 30000), "disk detach deadline missing");
        if (Commands.size() == 2)
            Require(Commands[1] == make_pair(string("/sbin/umount"), 10000), "auxiliary unmount deadline missing");
    };
    attempt("/usr/bin/hdiutil", L"disk image detach", 1);
    attempt("/sbin/umount", L"auxiliary unmount", 2);
    Commands.clear();
    TimeoutCommand.clear();
    const int queriesBeforeContention = Queries;
    {
        const int otherDismount = FSKit::AcquireUnmountLock(mounted->AuxMountPoint);
        finally_do_arg(int, otherDismount, { close(finally_arg); });
        bool busy = false;
        try { core.DismountVolume(mounted, false, false); }
        catch (const MountedVolumeInUse &) { busy = true; }
        Require(busy && Queries == queriesBeforeContention && Commands.empty(),
                "competing dismount reached disk image discovery or detach");
    }
    for (const auto &failure : vector<pair<int, string>>{{1, "Resource busy"}, {EBUSY, ""}}) {
        ImageDetachStatus = failure.first;
        ImageDetachError = failure.second;
        Commands.clear();
        bool busy = false;
        try { core.DismountVolume(mounted, false, false); }
        catch (const MountedVolumeInUse &) { busy = true; }
        catch (const ExecutedProcessFailed &) { }
        Require(busy && Commands == vector<pair<string, int>>{{"/usr/bin/hdiutil", 30000}},
                "busy disk was not preserved or reported using its exit status");
    }
    for (bool force : {false, true}) {
        ImageDetachStatus = force ? EBUSY : EIO;
        Commands.clear();
        bool preserved = false;
        try { core.DismountVolume(mounted, force, false); }
        catch (const ExecutedProcessFailed &error) { preserved = error.GetExitCode() == ImageDetachStatus; }
        Require(preserved && Commands == vector<pair<string, int>>{{"/usr/bin/hdiutil", 30000}},
                "an unrelated or forced detach failure was changed");
    }
    ImageDetachStatus = 0;
    Commands.clear();
    DismountArguments.clear();
    InventoryAfterDetach = Read(root + "/unrelated");
    const int queriesBeforeSuccess = Queries;
    core.DismountVolume(mounted, false, false);
    Require(Queries == queriesBeforeSuccess + 3 && Commands.size() == 3 && Commands.back().first == "wait",
            "confirmed exact-image absence did not permit worker cleanup after disk-number reuse");
    Require(DismountArguments == vector<list<string>>{{"detach", "/dev/disk42"}, {"--", mounted->AuxMountPoint}},
            "ordinary FSKit teardown forced an unmount");
    InventoryAfterDetach = Read(root + "/absent");

    DismountArguments.clear();
    core.DismountVolume(mounted, true, false);
    Require(DismountArguments == vector<list<string>>{{"detach", "/dev/disk42", "-force"}, {"-f", "--", mounted->AuxMountPoint}},
            "explicit force did not reach both FSKit teardown steps");

    for (bool force : {false, true}) {
        for (bool retry : {false, true}) {
            MountValidations = 0;
            RefuseValidation = retry ? 4 : 3;
            AuxiliaryUnmountFailures = retry ? 1 : 0;
            DismountArguments.clear();
            list<string> detach = {"detach", "/dev/disk42"};
            list<string> unmount = {"--", mounted->AuxMountPoint};
            if (force) {
                detach.push_back("-force");
                unmount.push_front("-f");
            }
            vector<list<string>> expected = {detach};
            if (retry) expected.push_back(unmount);

            bool changed = false;
            try { core.DismountVolume(mounted, force, false); }
            catch (const ParameterIncorrect &) { changed = true; }
            Require(changed && DismountArguments == expected,
                    "FSKit teardown tried an auxiliary unmount after identity validation failed");
        }
    }
    RefuseValidation = 0;

    Commands.clear();
    core.DismountVolume(mounted, false, true);
    Require(Commands == vector<pair<string, int>>{{"/usr/bin/hdiutil", 30000}, {"flush", 0},
                {"/sbin/umount", 10000}, {"wait", 0}} && GlobalSyncCalls == 0,
            "FSKit refresh did not flush only the captured image after detach");
    for (const auto protection : {VolumeProtection::None, VolumeProtection::HiddenVolumeReadOnly}) {
        mounted->Protection = protection;
        FlushFailure = true;
        Commands.clear();
        bool flushUnconfirmed = false;
        try { core.DismountVolume(mounted, false, false); }
        catch (const DismountServiceCleanupFailed &e) { flushUnconfirmed = e.Reason.find(L"flush") != wstring::npos; }
        Require(flushUnconfirmed && Commands == vector<pair<string, int>>{{"/usr/bin/hdiutil", 30000}, {"flush", 0}},
                "failed flush for a writable volume did not preserve the backing worker");
        FlushFailure = false;
        Commands.clear();
        core.DismountVolume(mounted, false, false);
        Require(Commands == vector<pair<string, int>>{{"/usr/bin/hdiutil", 30000}, {"flush", 0},
                    {"/sbin/umount", 10000}, {"wait", 0}},
                "successful writable dismount skipped the encrypted-file sync");
    }
    mounted->Protection = VolumeProtection::None;

    DismountMountPoint.clear();
    mounted->AuxMountPoint = string(mounted->AuxMountPoint).substr(string("/private").size());
    Commands.clear();
    DismountArguments.clear();
    core.DismountVolume(mounted, true, true);
    Require(Commands == vector<pair<string, int>>{{"/usr/bin/hdiutil", 0}, {"/sbin/umount", 0}},
            "legacy auxiliary path inherited the FSKit deadlines");
    Require(DismountArguments == vector<list<string>>{{"detach", "/dev/disk42", "-force"}, {"--", mounted->AuxMountPoint}},
            "legacy auxiliary unmount inherited the FSKit force argument");
    Require(GlobalSyncCalls == 1, "legacy teardown skipped system sync");
}
int main(int argc, char **argv) {
    try {
        std::string root=argv[1], image=argv[2];
        CheckLocalMacReservation(root, image);
        for (const auto &name : {"exact", "alias", "exact_after_unknown", "exact_before_unknown", "same_attachment"}) {
            DevicePath device; DirectoryPath mount;
            Require(FindDiskImageInfoByImagePath(Read(root+"/"+name),image,device,mount), "positive match lost");
            Require(device=="/dev/disk42" && mount=="/Volumes/unit", "wrong mapping");
        }
        for (const auto &name : {"absent", "unrelated"}) {
            DevicePath device; DirectoryPath mount;
            Require(!FindDiskImageInfoByImagePath(Read(root+"/"+name),image,device,mount), "false match");
        }
        Inventory = Read(root + "/absent");
        const DirectoryPath vanishedBacking = root + "/removed-auxiliary";
        Require(FSKit::GetAttachedDiskImageDevice(vanishedBacking).IsEmpty(),
                "an empty image inventory depended on the backing path");
        Inventory = Read(root + "/retained_after_auxiliary_loss");
        Require(!FSKit::IsDiskImageAbsentAfterAuxiliaryUnmount(vanishedBacking),
                "a retained disk image was missed after its auxiliary mount disappeared");
        Inventory = Read(root + "/unrelated");
        Require(FSKit::IsDiskImageAbsentAfterAuxiliaryUnmount(vanishedBacking),
                "an unrelated disk image prevented confirmed absence after auxiliary mount loss");
        Inventory = Read(root + "/unknown_record");
        bool unknownAfterLoss = false;
        try { FSKit::IsDiskImageAbsentAfterAuxiliaryUnmount(vanishedBacking); }
        catch (const std::exception &) { unknownAfterLoss = true; }
        Require(unknownAfterLoss, "an incomplete image inventory confirmed worker exit after auxiliary mount loss");
        for (const auto &name : {"unknown_alias", "unknown_record", "bad_entities", "broken"}) {
            bool failed=false; DevicePath device; DirectoryPath mount;
            try { FindDiskImageInfoByImagePath(Read(root+"/"+name),image,device,mount); }
            catch(std::exception &) { failed=true; }
            Require(failed, "unknown inventory treated as absent");
        }
        VolumeInfoList volumes;
        for(int i=0;i<3;++i) { auto volume=std::make_shared<VolumeInfo>(); volume->AuxMountPoint=image.substr(0,image.rfind('/')); volumes.push_back(volume); }
        CoreMacOSX core;
        Queries=0; Inventory=Read(root+"/exact"); core.UpdateMountedVolumesInfo(volumes);
        Require(Queries==1, "more than one inventory per enumeration");
        for(auto volume:volumes)Require(volume->Discovery==VolumeInfo::ImageAttached, "attached status");
        for (const auto *record : {"conflicting_exact", "broken"}) {
            Inventory = Read(root + "/" + record);
            core.UpdateMountedVolumesInfo(volumes);
            for (auto volume : volumes)
                Require(volume->Discovery == VolumeInfo::DiscoveryUnknown && volume->VirtualDevice.empty()
                        && volume->MountPoint.empty(), "ambiguous or unreadable inventory published an attachment");
        }
        Inventory=Read(root+"/absent"); core.UpdateMountedVolumesInfo(volumes);
        for(auto volume:volumes)Require(volume->Discovery==VolumeInfo::ImageAbsent, "absent status");
        Inventory=Read(root+"/exact"); core.UpdateMountedVolumeInfo(volumes.front());
        Require(Queries==5 && volumes.front()->VirtualDevice=="/dev/disk42", "destructive lookup reused display snapshot");
        std::cout << "PASS: exact and alias matches, conflicting and incomplete inventories, batch queries, and fresh lookup\n";
        Inventory = Read(root + "/exact");
        CheckDismount(core, image, root);
        std::cout << "PASS: FSKit deadlines, busy preservation, ambiguous attachments, cleanup ordering, identity and force\n";
        AttachReply = Read(root + "/attach");
        CheckAttach(core, image.substr(0, image.rfind('/')));
        CheckKernelFat(core, image.substr(0, image.rfind('/')), root);
        cout << "PASS: kernel FAT12/16/32 selection, mount directories, access modes, timeouts, and fail-closed identity checks\n";
        std::cout << "PASS: FSKit attach deadline, read-only and attach-only flags, and one compatibility retry\n";
        CheckStartupRollback();
        std::cout << "PASS: startup rollback preserves identity, cleanup warnings, and the eject observer handoff\n";
        CheckMediaObservation();
        std::cout << "PASS: verified media is observed directly and incomplete attachment evidence requests a bounded lookup\n";
        SlotViewTest::CheckVisibleSlots();
        std::cout << "PASS: volume views select the first entry for each valid slot\n";
        SlotViewTest::CheckCollidingMountSerials();
        std::cout << "PASS: macOS volume events and logout retain distinct mounts with the same serial\n";
        SlotViewTest::CheckInactivitySampling();
        std::cout << "PASS: per-mount inactivity uses fresh observations and resets for replacements\n";
        SlotViewTest::CheckOpenSelectedVolume();
        std::cout << "PASS: Finder opens require a fresh visible volume identity\n";
        CheckLateWorkerPublication();
        std::cout << "PASS: late publication, cancellation, worker retention, and exit after disk image release\n";
        CheckAuxiliaryMountStartup();
        std::cout << "PASS: auxiliary mount deadline and confirmed and unconfirmed worker cleanup\n";
        CheckWorkerTeardown(root + "/unused-mount");
        std::cout << "PASS: unmount lock, transient mount absence, and worker exit\n";
        CheckExternalEjectCleanup(root, image);
        std::cout << "PASS: external eject cleanup requires known disk absence and the original filesystem under the teardown lock\n";
        CheckBackingReservation(root, image);
        std::cout << "PASS: backing-file reservation, hard-link rejection, independent files, and reuse after release\n";
        CheckSlotReservation(root);
        std::cout << "PASS: explicit slot contention, automatic fallback, and slot reuse after release\n";
    } catch(std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
'''
        slot_view_fixture = r'''
namespace SlotViewTest {
struct VolumeDiscoveryResult {
    VolumeInfoList Volumes;
    list<DirectoryPath> UnresolvedMounts;
    bool IsComplete() const { return UnresolvedMounts.empty(); }
};
struct CoreFixture {
    VolumeDiscoveryResult Discovery;
    bool IsSlotNumberValid(VolumeSlotNumber slot) const { return slot >= 1 && slot <= 64; }
    VolumeDiscoveryResult GetMountedVolumesWithStatus() const { return Discovery; }
};
static CoreFixture core;
static const auto *Core = &core;
''' + slot_view + r'''
static void CheckVisibleSlots() {
    auto make = [](VolumeSlotNumber slot, VolumeInfo::DiscoveryState discovery) {
        auto volume = make_shared<VolumeInfo>();
        volume->SlotNumber = slot;
        volume->Discovery = discovery;
        return volume;
    };
    const auto live = make(4, VolumeInfo::ImageAttached);
    const auto unreadable = make(4, VolumeInfo::ControlUnavailable);
    const auto other = make(2, VolumeInfo::ControlUnavailable);
    const auto invalid = make(0, VolumeInfo::ImageAttached);
    const auto slots = GetMountedVolumesBySlot({live, unreadable, other, invalid});
    if (slots.size() != 2 || slots.begin()->second != other || slots.at(4) != live)
        throw runtime_error("the volume views did not retain the first valid entry per slot");
}

using VeraCrypt::VolumeSnapshotState;
struct wxBusyCursor {};
struct MenuGui {
    DirectoryPath Opened;
    VolumeInfoList InactiveVolumes;
    unsigned Warnings = 0;
    bool Waiting = false;
    bool GetWaitDialog() const { return Waiting; }
    void OpenExplorerWindow(const DirectoryPath &path) { Opened = path; }
    void ShowWarning(const char *) { ++Warnings; }
    void ShowError(const exception &) { throw; }
    void AutoDismountVolumes(const VolumeInfoList &volumes, bool force) {
        if (force) throw runtime_error("idle timer forced dismount");
        InactiveVolumes = volumes;
    }
};
static MenuGui gui;
static auto *Gui = &gui;
struct LanguageStrings {
    const char *operator[](const char *key) const { return key; }
};
static const LanguageStrings LangString;
struct VolumeListChange { bool Mounted; shared_ptr<VolumeInfo> Volume; };
struct wxThreadEvent {
    VolumeListChange Change;
    template <typename T> T GetPayload() const { return Change; }
};
struct VolumeDiscoveryState { int AccessMutex = 0; uint64 Generation = 0; };
struct ScopeLock { explicit ScopeLock(int &) {} };
using wxLongLong = long long;
static VolumeSnapshotState::Clock::time_point TestNow;
class MainFrame {
public:
    VolumeInfoList MountedVolumes;
    VolumeSnapshotState VolumeSnapshot;
    shared_ptr<VolumeDiscoveryState> VolumeDiscovery = make_shared<VolumeDiscoveryState>();
    unsigned Refreshes = 0;
    shared_ptr<VolumeInfo> GetSelectedVolume() const { return MountedVolumes.front(); }
    void OpenSelectedVolume() const;
    void OpenMountedVolume(const shared_ptr<VolumeInfo> &selected) const;
    void OnUpdateVolumeList(wxThreadEvent &event);
    void UpdateVolumeList() { ++Refreshes; }
    struct Preferences { bool DismountOnInactivity = true; int MaxVolumeIdleTime = 1; } Prefs;
    const Preferences &GetPreferences() const { return Prefs; }
    void CheckInactivity();
#define TC_MACOSX
''' + activity_types + activity_member + r'''
#undef TC_MACOSX
};
class GraphicUserInterface {
public:
    VolumeInfoList Captured;
    VolumeInfoList GetMountedVolumesForUI() const { return Captured; }
    VolumeInfoList GetVolumesForAutoDismount() const;
};
#define TC_MACOSX
''' + open_volume + volume_event + auto_dismount + r'''
void MainFrame::CheckInactivity() {
''' + idle_timer + r'''
}
#undef TC_MACOSX
static void RetainSnapshotRows(VolumeDiscoveryResult &result, const VolumeInfoList &MountedVolumes) {
''' + snapshot_retention + r'''
}

static void CheckCollidingMountSerials() {
    auto a = make_shared<VolumeInfo>();
    a->SerialInstanceNumber = 42;
    a->SlotNumber = 1;
    a->Path = "/disposable-a.hc";
    a->AuxMountPoint = "/disposable-aux-a";
    a->Discovery = VolumeInfo::ImageAttached;
    a->MountPoint = "/disposable-a-mount";
    a->VirtualDevice = "/dev/disk42";
    auto b = make_shared<VolumeInfo>(*a);
    b->SlotNumber = 2;
    b->Path = "/disposable-b.hc";
    b->AuxMountPoint = "/disposable-aux-b";

    MainFrame frame;
    frame.MountedVolumes = {a, b};
    frame.VolumeSnapshot.RecordSample(VolumeSnapshotState::Clock::now(), true);
    wxThreadEvent dismounted{{false, make_shared<VolumeInfo>(*a)}};
    frame.OnUpdateVolumeList(dismounted);
    if (frame.MountedVolumes != VolumeInfoList{b} || frame.VolumeSnapshot.IsFresh() || frame.Refreshes != 1)
        throw runtime_error("dismount event removed a different mount with the same serial");

    auto replacement = make_shared<VolumeInfo>(*a);
    replacement->AuxMountPoint = "/disposable-aux-replacement";
    frame.MountedVolumes = {replacement};
    frame.OnUpdateVolumeList(dismounted);
    if (frame.MountedVolumes != VolumeInfoList{replacement})
        throw runtime_error("old dismount event removed the replacement auxiliary mount");

    GraphicUserInterface ui;
    core.Discovery.Volumes = {b};
    core.Discovery.UnresolvedMounts = {a->AuxMountPoint};
    ui.Captured = {a, b};
    if (ui.GetVolumesForAutoDismount() != VolumeInfoList{b, a})
        throw runtime_error("logout lost an unreadable mount which shared a live mount's serial");

    VolumeDiscoveryResult snapshot = core.Discovery;
    RetainSnapshotRows(snapshot, ui.Captured);
    auto retained = snapshot.Volumes.back();
    if (snapshot.Volumes.size() != 2 || retained == a || !retained->IsSameMountInstance(*a)
            || retained->Discovery != VolumeInfo::ControlUnavailable
            || !retained->MountPoint.IsEmpty() || !retained->VirtualDevice.IsEmpty())
        throw runtime_error("partial discovery lost a distinct unreadable mount or retained stale device details");

    core.Discovery.Volumes = {make_shared<VolumeInfo>(*a), b};
    if (ui.GetVolumesForAutoDismount() != core.Discovery.Volumes)
        throw runtime_error("logout tried the same mount instance more than once");

    snapshot = core.Discovery;
    RetainSnapshotRows(snapshot, ui.Captured);
    if (snapshot.Volumes != core.Discovery.Volumes)
        throw runtime_error("partial discovery duplicated the same mount instance");
}

static void CheckInactivitySampling() {
    auto first = make_shared<VolumeInfo>();
    first->Path = "/disposable-idle.hc";
    first->AuxMountPoint = "/disposable-idle-first";
    first->SlotNumber = 1;
    first->SerialInstanceNumber = 42;
    auto second = make_shared<VolumeInfo>(*first);
    second->Path = "/disposable-active.hc";
    second->AuxMountPoint = "/disposable-idle-second";
    second->SlotNumber = 2;
    MainFrame frame;
    const auto start = VolumeSnapshotState::Clock::now();
    auto observe = [&](int sampledAt, int receivedAt, const VolumeInfoList &volumes) {
        TestNow = start + chrono::seconds(receivedAt);
        frame.VolumeSnapshot.RecordSample(start + chrono::seconds(sampledAt), true);
        frame.MountedVolumes = volumes;
        gui.InactiveVolumes.clear();
        frame.CheckInactivity();
        return gui.InactiveVolumes;
    };
    observe(0, 0, {first, second});
    ++second->TotalDataRead;
    observe(59, 59, {first, second});
    if (!observe(59, 62, {first, second}).empty())
        throw runtime_error("an earlier discovery sample triggered idle dismount using the later GUI clock");

    auto unreadable = make_shared<VolumeInfo>(*first);
    unreadable->Discovery = VolumeInfo::ControlUnavailable;
    if (!observe(61, 62, {unreadable, second}).empty())
        throw runtime_error("stale counters from an unreadable worker triggered idle dismount");
    if (observe(62, 63, {first, second}) != VolumeInfoList{first})
        throw runtime_error("a new sample did not expire just the independently idle volume");

    auto replacement = make_shared<VolumeInfo>(*first);
    replacement->AuxMountPoint = "/disposable-idle-replacement";
    if (!observe(65, 65, {replacement, second}).empty())
        throw runtime_error("a replacement mount inherited the earlier mount's idle timer");

    ++second->TotalDataRead;
    observe(110, 114, {replacement, second});
    if (observe(171, 171, {replacement, second}) != VolumeInfoList{replacement})
        throw runtime_error("activity from a delayed observation expired too early");
    if (observe(175, 175, {replacement, second}) != VolumeInfoList{replacement, second})
        throw runtime_error("a replaced or active volume did not earn an independent idle deadline");
}

static void CheckOpenSelectedVolume() {
    MainFrame frame;
    auto volume = make_shared<VolumeInfo>();
    volume->SlotNumber = 4;
    volume->SerialInstanceNumber = 42;
    volume->Path = "/test.hc";
    volume->MountPoint = "/test-mount";
    volume->Discovery = VolumeInfo::ImageAttached;
    frame.MountedVolumes = {volume};
    frame.VolumeSnapshot.RecordSample(VolumeSnapshotState::Clock::now() - chrono::seconds(8), true);
    frame.OpenSelectedVolume();
    if (!gui.Opened.IsEmpty() || gui.Warnings != 1)
        throw runtime_error("main window opened a stale mount path");

    frame.VolumeSnapshot.RecordSample(VolumeSnapshotState::Clock::now(), false);
    frame.OpenSelectedVolume();
    if (gui.Opened != volume->MountPoint || gui.Warnings != 1)
        throw runtime_error("main window refused a fresh mounted volume during partial discovery");

    auto current = make_shared<VolumeInfo>(*volume);
    current->MountPoint = "/updated-mount";
    frame.MountedVolumes = {current};
    frame.OpenMountedVolume(volume);
    if (gui.Opened != current->MountPoint || gui.Warnings != 1)
        throw runtime_error("menu opened the captured path instead of the current mount point");

    gui.Opened.clear();
    ++current->SerialInstanceNumber;
    frame.OpenMountedVolume(volume);
    if (!gui.Opened.IsEmpty() || gui.Warnings != 2)
        throw runtime_error("menu opened a replacement volume in the same slot");

    --current->SerialInstanceNumber;
    current->AuxMountPoint = "/replacement-auxiliary";
    frame.OpenMountedVolume(volume);
    if (!gui.Opened.IsEmpty() || gui.Warnings != 3)
        throw runtime_error("menu opened a different auxiliary mount with the same serial, path, and slot");

    gui.Waiting = true;
    frame.OpenSelectedVolume();
    if (!gui.Opened.IsEmpty() || gui.Warnings != 3)
        throw runtime_error("main window tried to open a volume while an operation was pending");
}
}
'''
        unit = work / "discovery.cpp"
        unit.write_text(prelude + slot_view_fixture + helpers + attached_device + "\n#define sync CountGlobalSync\n" + dismount + "\n#undef sync\n"
                        + refresh + device_name_check + attach + rollback_fixture + observation_fixture + auxiliary_fixture
                        + mount_guard_fixture + publication_fixture + tests)
        command = ["clang++", "-std=c++11", "-DVC_MACOSX_FSKIT", "-I" + str(ROOT / "src"), str(unit), "-framework", "CoreFoundation", "-o", str(work / "discovery")]
        subprocess.run(command, check=True)
        subprocess.run([str(work / "discovery"), str(work), str(image)], check=True, timeout=20)
        if args.platform_archive:
            command = ["clang++", "-std=c++11", "-DTC_UNIX", "-DTC_MACOSX", "-I" + str(ROOT / "src"), str(ROOT / "Tests/macos_process_test.cpp"), str(args.platform_archive.resolve()), "-Wl,-dead_strip", "-o", str(work / "process")]
            subprocess.run(command, check=True)
            subprocess.run([str(work / "process")], check=True, timeout=20)
            command = ["clang++", "-std=c++11", "-DTC_UNIX", "-DTC_MACOSX", "-I" + str(ROOT / "src"), str(ROOT / "Tests/macos_volume_state_test.cpp"), str(args.platform_archive.resolve()), "-Wl,-dead_strip", "-o", str(work / "state")]
            subprocess.run(command, check=True)
            subprocess.run([str(work / "state")], check=True, timeout=20)


if __name__ == "__main__":
    main()
