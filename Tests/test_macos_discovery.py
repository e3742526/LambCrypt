#!/usr/bin/env python3
"""Unit checks for macOS discovery and FSKit attach and teardown without mounts.

Compiles the production plist helpers and batch-refresh methods with a fake
inventory provider, so tests can supply incomplete inventories safely. Optional
--platform-archive runs the real bounded process runner from a matching build.
"""
import argparse
from pathlib import Path
import plistlib
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
        cases = {
            "exact": {"images": [exact]},
            "alias": {"images": [alias_image]},
            "absent": {"images": []},
            "unrelated": {"images": [{"image-path": "/offline/unrelated.dmg"}]},
            "exact_after_unknown": {"images": [unknown_alias, {}, exact]},
            "unknown_alias": {"images": [unknown_alias]},
            "unknown_record": {"images": [{}]},
            "bad_entities": {"images": [{"image-path": str(image.resolve())}]},
        }
        for name, contents in cases.items():
            (work / name).write_bytes(plistlib.dumps(contents))
        (work / "attach").write_bytes(plistlib.dumps({"system-entities": exact["system-entities"]}))
        (work / "broken").write_text("invalid plist")

        source = (ROOT / "src/Core/Unix/MacOSX/CoreMacOSX.cpp").read_text()
        helpers = source[source.index("\tclass CFHolder"):source.index("\tCoreMacOSX::CoreMacOSX ()")]
        dismount = source[source.index("\tshared_ptr <VolumeInfo> CoreMacOSX::DismountVolume"):
                          source.index("\tstatic void ClearDiskImageInfo")]
        refresh = source[source.index("\tstatic void ClearDiskImageInfo"):source.index("\t// Strict /dev/diskN")]
        attach = source[source.index("\tDevicePath CoreMacOSX::MountAuxVolumeImage"):
                        source.index("\tunique_ptr <CoreBase> Core (")]
        unix_source = (ROOT / "src/Core/Unix/CoreUnix.cpp").read_text()
        mount_end = unix_source.index("\n\t}\n\n\tDevicePath CoreUnix::MountAuxVolumeImage")
        rollback_start = unix_source.rindex("\n\t\t\treturn mountedVolume;\n\t\t}", 0, mount_end)
        rollback = unix_source[rollback_start:mount_end].split("\n\t\t}", 1)[1]
        prelude = r'''
#include "Platform/Finally.h"
#include <CoreFoundation/CoreFoundation.h>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <algorithm>
#include <cstdlib>
#include <unistd.h>
#include <vector>
#define throw_sys_sub_if(condition, subject) do { if (condition) throw std::runtime_error(subject); } while(false)
using namespace std;
#undef SRC_POS
#define SRC_POS "test source"
#define VERSION_NUM 1
using uint64 = uint64_t;
using DevicePath = std::string;
struct DirectoryPath : std::string {
    using std::string::string;
    DirectoryPath() {}
    DirectoryPath(const std::string &s) : std::string(s) {}
    bool IsEmpty() const { return empty(); }
    bool IsBlockDevice() const { return find("/dev/disk") == 0; }
    explicit operator wstring() const { return wstring(begin(), end()); }
};
struct ParameterIncorrect : std::runtime_error { ParameterIncorrect(const std::string &s) : std::runtime_error(s) {} };
struct VolumeDiscoveryFailed : std::runtime_error { VolumeDiscoveryFailed(const std::string &s, const std::wstring &) : std::runtime_error(s) {} };
struct DismountServiceCleanupFailed {
    DismountServiceCleanupFailed(const string &, const wstring &reason) : Reason(reason) {}
    wstring Reason;
};
struct MountServiceCleanupFailed {
    MountServiceCleanupFailed(const string &, const wstring &reason) : Reason(reason) {}
    wstring Reason;
};
struct MountedVolumeInUse { explicit MountedVolumeInUse(const string &) {} };
struct TimeOut {};
struct ExecutedProcessFailed {
    explicit ExecutedProcessFailed(string error) : Error(error) {}
    string GetErrorOutput() const { return Error; }
    string Error;
};
struct StringConverter {
    static std::string Trim(std::string s) { size_t b=s.find_first_not_of(" \t\r\n"); if(b==std::string::npos)return ""; return s.substr(b,s.find_last_not_of(" \t\r\n")-b+1); }
    static std::wstring ToWide(const std::string &s) { return wstring(s.begin(), s.end()); }
    static std::wstring ToExceptionString(const std::exception &) { return L"failure"; }
};
static std::string Inventory;
static int Queries;
static vector<pair<string, int>> Commands;
static string TimeoutCommand;
static bool BusyImage;
static vector<list<string>> AttachCommands;
static string AttachReply;
static int AttachOptionFailures;
struct Process {
    static string ExecuteBounded(const string &path, const list<string> &arguments, int deadline) {
        if (arguments.front() == "info") {
            if (deadline != 2000) throw runtime_error("discovery deadline");
            ++Queries;
            return Inventory;
        }
        Commands.emplace_back(path, deadline);
        if (path == TimeoutCommand) throw TimeOut{};
        if (BusyImage && arguments.front() == "detach") throw ExecutedProcessFailed("Resource busy");
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
};
struct FuseService { static std::string GetVolumeImagePath() { return "/volume.dmg"; } };
namespace FSKit {
    static void WaitForServiceExit(const DirectoryPath &) { Commands.emplace_back("wait", 0); }
}
namespace Thread { static void Sleep(int) {} }
namespace VolumeProtection { enum { None, HiddenVolumeReadOnly, ReadOnly }; }
struct MountOptions {
    bool NoFilesystem = false;
    shared_ptr<DirectoryPath> MountPoint, Path;
    int Protection = VolumeProtection::None;
    unsigned int SlotNumber = 2;
};
struct SystemLog { static void WriteException(const std::exception &) {} };
#define foreach(declaration, collection) for (declaration : collection)
struct Volume {
    string Path;
};
struct VolumeInfo {
    enum DiscoveryState { DiscoveryUnknown, ImageAttached, ImageAbsent, ControlUnavailable };
    DiscoveryState Discovery = DiscoveryUnknown;
    DirectoryPath AuxMountPoint, MountPoint;
    DevicePath VirtualDevice;
    int Protection = VolumeProtection::None;
    string Path;
    unsigned int ProgramVersion = 0, SlotNumber = 0;
    uint64 SerialInstanceNumber = 0;
    void Set(const Volume &volume) { Path = volume.Path; }
};
using VolumeInfoList = std::list<std::shared_ptr<VolumeInfo>>;
struct MountedFilesystem { DirectoryPath MountPoint; };
using MountedFilesystemList = std::list<std::shared_ptr<MountedFilesystem>>;
class CoreMacOSX {
public:
    shared_ptr<VolumeInfo> DismountVolume(shared_ptr<VolumeInfo>, bool, bool);
    shared_ptr<VolumeInfo> ValidateMountedVolume(shared_ptr<VolumeInfo> volume) const { return volume; }
    void UpdateMountedVolumesInfo(VolumeInfoList &) const;
    void UpdateMountedVolumeInfo(std::shared_ptr<VolumeInfo>) const;
    void UpdateMountedVolumeInfo(std::shared_ptr<VolumeInfo>, const std::string &) const;
    MountedFilesystemList GetMountedFilesystems(const DevicePath &) const { return {}; }
    string GetDefaultMountPointPrefix() const { return "/Volumes/Untitled"; }
    DevicePath MountAuxVolumeImage(const DirectoryPath &, const MountOptions &) const;
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
static shared_ptr<VolumeInfo> RollbackTarget;

static shared_ptr<VolumeInfo> GetMountedVolume(const DirectoryPath &) {
    auto replacement = make_shared<VolumeInfo>();
    replacement->Path = StartupContainer;
    replacement->AuxMountPoint = "/private/tmp/lambcrypt-fskit.replacement/.veracrypt_aux_mnt";
    replacement->SerialInstanceNumber = StartupSerial + 1;
    return replacement;
}

static void DismountVolume(shared_ptr<VolumeInfo> volume) {
    RollbackTarget = volume;
    if (RefuseRollback) throw runtime_error("worker identity unavailable");
}

static void SimulateStartupFailure(bool unconfirmedAttach) {
    const string fuseMountPoint = StartupAuxiliary;
    const uint64 mountServiceSerialInstanceNumber = StartupSerial;
    auto volume = make_shared<Volume>();
    volume->Path = StartupContainer;
    MountOptions options;
    options.Path = make_shared<DirectoryPath>(StartupContainer);
    try {
        if (unconfirmedAttach)
            throw MountServiceCleanupFailed(SRC_POS, L"attach remains unconfirmed");
        throw runtime_error("startup failed");
    }
''' + rollback + "\n}\n"
        tests = r'''
static void Require(bool condition, const char *message) { if(!condition)throw std::runtime_error(message); }
static std::string Read(const std::string &path) { std::ifstream f(path); return std::string(std::istreambuf_iterator<char>(f), {}); }
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

    reset();
    TimeoutCommand = "/usr/bin/hdiutil";
    bool unconfirmed = false;
    try { core.MountAuxVolumeImage(auxiliary, options); }
    catch (const MountServiceCleanupFailed &e) {
        unconfirmed = e.Reason == L"macOS did not confirm disk image attach: " + wstring(auxiliary);
    }
    TimeoutCommand.clear();
    Require(unconfirmed && Commands.size() == 1, "attach timeout lost its cleanup state or attempted another command");

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
static void CheckStartupRollback() {
    bool keptStartupError = false;
    try { SimulateStartupFailure(false); }
    catch (const runtime_error &e) { keptStartupError = string(e.what()) == "startup failed"; }
    Require(keptStartupError && RollbackTarget && RollbackTarget->AuxMountPoint == StartupAuxiliary
            && RollbackTarget->SerialInstanceNumber == StartupSerial && RollbackTarget->SlotNumber == 2
            && RollbackTarget->Path == StartupContainer, "startup rollback used a replacement mount identity");

    RefuseRollback = true;
    bool warnedOfFailure = false;
    try { SimulateStartupFailure(false); }
    catch (const MountServiceCleanupFailed &e) {
        warnedOfFailure = e.Reason == StringConverter::ToWide(StartupAuxiliary) + L"\nfailure";
    }
    Require(warnedOfFailure, "startup rollback failure was hidden");

    RollbackTarget.reset();
    bool keptAttachWarning = false;
    try { SimulateStartupFailure(true); }
    catch (const MountServiceCleanupFailed &e) { keptAttachWarning = e.Reason == L"attach remains unconfirmed"; }
    Require(keptAttachWarning && !RollbackTarget, "startup rollback attempted cleanup after an unconfirmed attach");
}
static void CheckDismount(CoreMacOSX &core, const string &image) {
    auto mounted = make_shared<VolumeInfo>();
    mounted->AuxMountPoint = image.substr(0, image.rfind('/'));
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
    BusyImage = true;
    bool busy = false;
    try { core.DismountVolume(mounted, false, false); }
    catch (const MountedVolumeInUse &) { busy = true; }
    Require(busy && Commands.size() == 1, "busy disk was not preserved");
    BusyImage = false;
    Commands.clear();
    core.DismountVolume(mounted, false, false);
    Require(Commands.size() == 3 && Commands.back().first == "wait", "successful detach skipped worker wait");

    mounted->AuxMountPoint = string(mounted->AuxMountPoint).substr(string("/private").size());
    Commands.clear();
    core.DismountVolume(mounted, false, false);
    Require(Commands == vector<pair<string, int>>{{"/usr/bin/hdiutil", 0}, {"/sbin/umount", 0}},
            "legacy auxiliary path inherited the FSKit deadlines");
}
int main(int argc, char **argv) {
    try {
        std::string root=argv[1], image=argv[2];
        for (const auto &name : {"exact", "alias", "exact_after_unknown"}) {
            DevicePath device; DirectoryPath mount;
            Require(FindDiskImageInfoByImagePath(Read(root+"/"+name),image,device,mount), "positive match lost");
            Require(device=="/dev/disk42" && mount=="/Volumes/unit", "wrong mapping");
        }
        for (const auto &name : {"absent", "unrelated"}) {
            DevicePath device; DirectoryPath mount;
            Require(!FindDiskImageInfoByImagePath(Read(root+"/"+name),image,device,mount), "false match");
        }
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
        Inventory=Read(root+"/broken"); core.UpdateMountedVolumesInfo(volumes);
        for(auto volume:volumes)Require(volume->Discovery==VolumeInfo::DiscoveryUnknown && volume->VirtualDevice.empty() && volume->MountPoint.empty(), "stale device survived failure");
        Inventory=Read(root+"/absent"); core.UpdateMountedVolumesInfo(volumes);
        for(auto volume:volumes)Require(volume->Discovery==VolumeInfo::ImageAbsent, "absent status");
        Inventory=Read(root+"/exact"); core.UpdateMountedVolumeInfo(volumes.front());
        Require(Queries==4 && volumes.front()->VirtualDevice=="/dev/disk42", "destructive lookup reused display snapshot");
        std::cout << "PASS: exact/alias matches, unrelated and incomplete inventories, batch query count, unknown/absent states, fresh lookup\n";
        Inventory = Read(root + "/exact");
        CheckDismount(core, image);
        std::cout << "PASS: FSKit detach and unmount deadlines, busy preservation, successful cleanup ordering\n";
        AttachReply = Read(root + "/attach");
        CheckAttach(core, image.substr(0, image.rfind('/')));
        std::cout << "PASS: FSKit attach deadline, read-only and attach-only flags, and one compatibility retry\n";
        CheckStartupRollback();
        std::cout << "PASS: startup rollback preserves identity and reports unconfirmed cleanup\n";
    } catch(std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
'''
        unit = work / "discovery.cpp"
        unit.write_text(prelude + helpers + dismount + refresh + attach + rollback_fixture + tests)
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
