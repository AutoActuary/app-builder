function Initialize-AppBuilderFileChecks {
    if ('AppBuilderFiles' -as [type]) { return }
    if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
        throw 'File inspection requires 64-bit PowerShell on 64-bit Windows.'
    }
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

public static class AppBuilderFiles {
    [StructLayout(LayoutKind.Sequential)] struct ProcessIdentity {
        public uint Id;
        public System.Runtime.InteropServices.ComTypes.FILETIME Started;
    }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] struct ResourceUser {
        public ProcessIdentity Process;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string Name;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)] public string Service;
        public uint Type, Status, Session;
        [MarshalAs(UnmanagedType.Bool)] public bool Restartable;
    }
    [StructLayout(LayoutKind.Sequential)] struct MemoryRegion {
        public UIntPtr Address, Allocation;
        public uint AllocationProtection;
        public UIntPtr Size;
        public uint State, Protection, Type;
    }
    [StructLayout(LayoutKind.Sequential)] struct RenameInformation {
        public uint Flags;
        public IntPtr Root;
        public uint Length;
        public ushort FirstCharacter;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern IntPtr CreateFileW(string path, uint access, uint share, IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr OpenProcess(uint access, bool inherit, uint id);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll", SetLastError = true)] static extern UIntPtr VirtualQueryEx(IntPtr process, UIntPtr address, out MemoryRegion region, UIntPtr length);
    [DllImport("psapi.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern uint GetMappedFileNameW(IntPtr process, UIntPtr address, StringBuilder name, uint size);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern uint GetFinalPathNameByHandleW(IntPtr handle, StringBuilder name, uint size, uint flags);
    [DllImport("rstrtmgr.dll", CharSet = CharSet.Unicode)] static extern int RmStartSession(out uint session, uint flags, StringBuilder key);
    [DllImport("rstrtmgr.dll", CharSet = CharSet.Unicode)] static extern int RmRegisterResources(uint session, uint count, string[] files, uint processes, IntPtr identities, uint services, IntPtr serviceNames);
    [DllImport("rstrtmgr.dll")] static extern int RmGetList(uint session, out uint needed, ref uint count, [In, Out] ResourceUser[] users, out uint reasons);
    [DllImport("rstrtmgr.dll")] static extern int RmEndSession(uint session);
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern IntPtr CommandLineToArgvW(string command, out int count);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr pointer);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool DeleteFileW(string path);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool RemoveDirectoryW(string path);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool SetFileAttributesW(string path, uint attributes);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool SetFileInformationByHandle(IntPtr handle, int kind, IntPtr information, uint size);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool MoveFileExW(string source, string destination, uint flags);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool GetDiskFreeSpaceExW(string path, out ulong available, out ulong total, out ulong free);

    public static string CheckSpace(string directory, ulong minimum) {
        if (minimum == 0) return null;
        string parent = Path.GetDirectoryName(Path.GetFullPath(directory));
        while (parent != null && !Directory.Exists(NativePath(parent))) parent = Path.GetDirectoryName(parent);
        if (parent == null) return directory + ": no accessible destination ancestor.";
        ulong available, total, free;
        if (!GetDiskFreeSpaceExW(NativePath(parent).TrimEnd('\\') + "\\", out available, out total, out free))
            return directory + ": cannot check available space: " + new Win32Exception(Marshal.GetLastWin32Error()).Message;
        return available < minimum ? directory + ": not enough available space to stage the payload (need at least " + minimum + " bytes; available " + available + ")." : null;
    }

    public static void Move(string source, string destination) {
        // No replacement or cross-volume copy flags: one same-volume rename.
        if (!MoveFileExW(NativePath(source), NativePath(destination), 0))
            throw new Win32Exception(Marshal.GetLastWin32Error(), source + " -> " + destination);
    }

    static int CheckRename(string path) {
        // Hold the source against concurrent renames while obtaining its name.
        IntPtr handle = CreateFileW(NativePath(path), 0x10000, 3, IntPtr.Zero, 3, 0x02200000, IntPtr.Zero);
        if (handle == new IntPtr(-1)) return Marshal.GetLastWin32Error();
        var ancestors = new List<IntPtr>();
        try {
            var current = new StringBuilder(32768);
            uint length = GetFinalPathNameByHandleW(handle, current, (uint)current.Capacity, 0);
            if (length == 0) return Marshal.GetLastWin32Error();
            if (length >= current.Capacity) return 206;
            string original = current.ToString();
            // Stabilize the full name: another process must not turn this
            // same-name check into a real rename by renaming an ancestor.
            string parent = Path.GetDirectoryName(original);
            while (parent != null && parent != Path.GetPathRoot(parent)) {
                IntPtr held = CreateFileW(parent, 0, 3, IntPtr.Zero, 3, 0x02000000, IntPtr.Zero);
                if (held == new IntPtr(-1)) return Marshal.GetLastWin32Error();
                ancestors.Add(held);
                parent = Path.GetDirectoryName(parent);
            }
            current.Clear();
            length = GetFinalPathNameByHandleW(handle, current, (uint)current.Capacity, 0);
            if (length == 0) return Marshal.GetLastWin32Error();
            if (length >= current.Capacity) return 206;
            if (current.ToString() != original) return 32;
            // MS-FSA 2.1.5.15.12: open descendants are checked before the
            // exact-same-name early return. There is no rename or rollback.
            // Win32 also consumes FileName as a NUL-terminated string, despite
            // FileNameLength excluding the terminator. Allocate both explicitly.
            byte[] name = Encoding.Unicode.GetBytes(current.ToString() + "\0");
            int offset = (int)Marshal.OffsetOf(typeof(RenameInformation), "FirstCharacter");
            IntPtr information = Marshal.AllocHGlobal(offset + name.Length);
            try {
                Marshal.WriteInt32(information, 0, 0);
                Marshal.WriteIntPtr(information, (int)Marshal.OffsetOf(typeof(RenameInformation), "Root"), IntPtr.Zero);
                Marshal.WriteInt32(information, (int)Marshal.OffsetOf(typeof(RenameInformation), "Length"), name.Length - 2);
                Marshal.Copy(name, 0, IntPtr.Add(information, offset), name.Length);
                return SetFileInformationByHandle(handle, 3, information, (uint)(offset + name.Length)) ? 0 : Marshal.GetLastWin32Error();
            } finally { Marshal.FreeHGlobal(information); }
        } finally {
            foreach (IntPtr held in ancestors) CloseHandle(held);
            CloseHandle(handle);
        }
    }

    public static void RemoveTree(string root) {
        string path = NativePath(root);
        FileAttributes attributes = File.GetAttributes(path);
        bool directory = (attributes & FileAttributes.Directory) != 0;
        if (directory && (attributes & FileAttributes.ReparsePoint) == 0)
            foreach (string child in Directory.EnumerateFileSystemEntries(path)) RemoveTree(child);
        if ((attributes & FileAttributes.ReadOnly) != 0 &&
            !SetFileAttributesW(path, (uint)(attributes & ~FileAttributes.ReadOnly)))
            throw new Win32Exception(Marshal.GetLastWin32Error(), DisplayPath(path));
        bool removed = directory ? RemoveDirectoryW(path) : DeleteFileW(path);
        if (!removed) throw new Win32Exception(Marshal.GetLastWin32Error(), DisplayPath(path));
    }

    public static bool CommandTargets(string command, string directory) {
        int count;
        IntPtr argv = CommandLineToArgvW(command, out count);
        if (argv == IntPtr.Zero) return false;
        try {
            string root = Path.GetFullPath(directory).TrimEnd('\\', '/');
            for (int i = 0; i < count; i++) {
                string token = Environment.ExpandEnvironmentVariables(Marshal.PtrToStringUni(Marshal.ReadIntPtr(argv, i * IntPtr.Size)));
                if (!Path.IsPathRooted(token)) continue;
                try {
                    string path = Path.GetFullPath(token).TrimEnd('\\', '/');
                    if (path.Equals(root, StringComparison.OrdinalIgnoreCase) || path.StartsWith(root + "\\", StringComparison.OrdinalIgnoreCase)) return true;
                } catch (ArgumentException) { }
            }
            return false;
        } finally { LocalFree(argv); }
    }

    static string NativePath(string path) {
        if (path.StartsWith(@"\\?\")) return path;
        return path.StartsWith(@"\\") ? @"\\?\UNC\" + path.Substring(2) : @"\\?\" + Path.GetFullPath(path);
    }
    static string DisplayPath(string path) {
        if (path.StartsWith(@"\\?\UNC\")) return @"\\" + path.Substring(8);
        return path.StartsWith(@"\\?\") ? path.Substring(4) : path;
    }
    static IntPtr Open(string path, uint access) {
        // OPEN_EXISTING, all share modes, inspect the link itself; never delete-on-close.
        return CreateFileW(NativePath(path), access, 7, IntPtr.Zero, 3, 0x02200000, IntPtr.Zero);
    }
    static int Probe(string path, uint access) {
        IntPtr handle = Open(path, access);
        if (handle == new IntPtr(-1)) return Marshal.GetLastWin32Error();
        CloseHandle(handle);
        return 0;
    }
    static string Identity(string path) {
        IntPtr handle = Open(path, 0);
        if (handle == new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error(), path);
        try {
            var name = new StringBuilder(32768);
            uint length = GetFinalPathNameByHandleW(handle, name, (uint)name.Capacity, 2);
            if (length == 0 || length >= name.Capacity) throw new Win32Exception(Marshal.GetLastWin32Error(), path);
            return name.ToString();
        } finally { CloseHandle(handle); }
    }
    static ResourceUser[] Users(string[] files) {
        uint session;
        int error = RmStartSession(out session, 0, new StringBuilder(33));
        if (error != 0) throw new Win32Exception(error);
        try {
            error = RmRegisterResources(session, (uint)files.Length, files, 0, IntPtr.Zero, 0, IntPtr.Zero);
            if (error != 0) throw new Win32Exception(error);
            uint count = 0, needed, reasons;
            var users = new ResourceUser[0];
            for (int attempt = 0; attempt < 5; attempt++) {
                error = RmGetList(session, out needed, ref count, users, out reasons);
                if (error == 0) { Array.Resize(ref users, (int)count); return users; }
                if (error != 234) throw new Win32Exception(error);
                count = needed;
                users = new ResourceUser[count];
            }
            throw new IOException("Applications changed repeatedly during the lock query. Check again.");
        } finally { RmEndSession(session); }
    }
    static bool IsImage(string path) {
        using (var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            return file.ReadByte() == 0x4d && file.ReadByte() == 0x5a;
    }
    static void FindImages(ResourceUser user, Dictionary<string, string> candidates, List<string> blockers) {
        IntPtr process = OpenProcess(0x0400, false, user.Process.Id);
        if (process == IntPtr.Zero) {
            int error = Marshal.GetLastWin32Error();
            if (error == 87) return; // Process exited; the real operation still checks for races.
            throw new Win32Exception(error, "Cannot inspect " + user.Name + " (PID " + user.Process.Id + ")");
        }
        try {
            ulong address = 0, previousAllocation = ulong.MaxValue;
            MemoryRegion region;
            while (VirtualQueryEx(process, new UIntPtr(address), out region, new UIntPtr((uint)Marshal.SizeOf(typeof(MemoryRegion)))) != UIntPtr.Zero) {
                ulong allocation = region.Allocation.ToUInt64();
                if (region.Type == 0x1000000 && allocation != previousAllocation) {
                    var name = new StringBuilder(32768);
                    if (GetMappedFileNameW(process, region.Allocation, name, (uint)name.Capacity) == 0)
                        throw new Win32Exception(Marshal.GetLastWin32Error(), "Cannot inspect mapped image in PID " + user.Process.Id);
                    string path;
                    if (candidates.TryGetValue(name.ToString(), out path))
                        blockers.Add(path + ": loaded by " + user.Name + " (PID " + user.Process.Id + "). Save work and close this application.");
                }
                previousAllocation = allocation;
                ulong next = region.Address.ToUInt64() + region.Size.ToUInt64();
                if (next <= address) break;
                address = next;
            }
            int error = Marshal.GetLastWin32Error();
            if (error != 87 && error != 0) throw new Win32Exception(error, "Cannot finish inspecting PID " + user.Process.Id);
        } finally { CloseHandle(process); }
    }
    public static string[] Check(string[] roots) {
        var blockers = new List<string>();
        var suspects = new List<string>();
        var images = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var pending = new Stack<KeyValuePair<string, bool>>();
        foreach (string root in roots) {
            string path = Path.GetFullPath(root);
            string parent = Path.GetDirectoryName(path);
            while (parent != null && !Directory.Exists(NativePath(parent))) parent = Path.GetDirectoryName(parent);
            if (parent == null) { blockers.Add(path + ": no accessible destination ancestor."); continue; }
            // FILE_ADD_SUBDIRECTORY on the nearest existing destination ancestor.
            int parentError = Probe(parent, 2);
            if (parentError != 0) blockers.Add(parent + ": cannot create the replacement directory: " + new Win32Exception(parentError).Message);
            try {
                FileAttributes attributes = File.GetAttributes(NativePath(path));
                if ((attributes & FileAttributes.ReparsePoint) != 0) {
                    blockers.Add(path + ": refusing to replace an installation or Start Menu directory that is a link.");
                    continue;
                }
                if ((attributes & FileAttributes.Directory) == 0) {
                    blockers.Add(path + ": the destination is a file, not a directory.");
                    continue;
                }
                pending.Push(new KeyValuePair<string, bool>(NativePath(path), true));
            } catch (FileNotFoundException) { }
              catch (DirectoryNotFoundException) { }
              catch (Exception error) { blockers.Add(path + ": cannot inspect: " + error.Message); }
        }
        while (pending.Count != 0) {
            var entry = pending.Pop();
            string path = entry.Key;
            string display = DisplayPath(path);
            try {
                FileAttributes attributes = File.GetAttributes(path);
                bool directory = (attributes & FileAttributes.Directory) != 0;
                bool link = (attributes & FileAttributes.ReparsePoint) != 0;
                bool renameBlocked = entry.Value;
                if (directory && !link && renameBlocked) {
                    int renameError = CheckRename(path);
                    renameBlocked = renameError != 0;
                    if (renameBlocked) blockers.Add(display + ": Windows cannot rename this directory: " + new Win32Exception(renameError).Message + " (Windows error " + renameError + ").");
                }
                if (!directory && !link && renameBlocked) suspects.Add(display);
                int error = Probe(path, 0x10000); // DELETE access and share-mode conflicts.
                if (error != 0) {
                    blockers.Add(display + ": " + new Win32Exception(error).Message + " (Windows error " + error + ").");
                    if (!directory && !link) suspects.Add(display);
                }
                if ((attributes & FileAttributes.ReadOnly) != 0) {
                    int attributeError = Probe(path, 0x100); // FILE_WRITE_ATTRIBUTES, needed to clear read-only during removal.
                    if (attributeError != 0) blockers.Add(display + ": cannot clear the read-only attribute: " + new Win32Exception(attributeError).Message);
                }
                // Images need not have an open file handle. A write-open asks the
                // filesystem to check image sections without writing any bytes.
                if (!directory && !link) {
                    int writeError = Probe(path, 2);
                    if (writeError != 0 && IsImage(path)) {
                        // A kernel sharing refusal is already a blocker. Owner
                        // lookup is diagnostic, and cannot turn it into a pass.
                        if (writeError == 32) blockers.Add(display + ": image write-sharing conflict. Close the application using this file.");
                        suspects.Add(display);
                        images[Identity(path)] = display;
                    }
                }
                if (directory && !link)
                    foreach (string child in Directory.EnumerateFileSystemEntries(path)) pending.Push(new KeyValuePair<string, bool>(child, renameBlocked));
            } catch (Exception error) { blockers.Add(display + ": cannot inspect: " + error.Message); }
        }
        if (suspects.Count != 0) {
            try {
                var unique = new HashSet<string>(suspects, StringComparer.OrdinalIgnoreCase);
                var files = new string[unique.Count];
                unique.CopyTo(files);
                foreach (ResourceUser user in Users(files)) {
                    if (images.Count != 0) FindImages(user, images, blockers);
                    if (blockers.Count != 0)
                        blockers.Add("Application using inspected files: " + user.Name + " (PID " + user.Process.Id + ").");
                }
            } catch (Exception error) { blockers.Add("Could not complete the lock inspection: " + error.Message); }
        }
        return blockers.ToArray();
    }
}
'@
}

function Assert-AppBuilderFilesAvailable {
    param([string[]]$Paths)
    Initialize-AppBuilderFileChecks
    while ($true) {
        $Blockers = @([AppBuilderFiles]::Check($Paths))
        if ($Blockers.Count -eq 0) { return }
        $Message = "Cannot replace these files:`n" + ($Blockers -join "`n")
        if (-not (Request-AppBuilderRetry $Message)) { throw $Message }
    }
}
