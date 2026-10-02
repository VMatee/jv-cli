// The launcher owns Python from process creation, including abrupt launcher death.
// No shell, prompt transport, environment serialization or runtime downloads.
using System;
using System.IO;
using System.Text;
using System.Runtime.InteropServices;
using System.ComponentModel;

class Launcher {
    [StructLayout(LayoutKind.Sequential)] struct SI {
        public uint cb; public IntPtr reserved, desktop, title;
        public uint x,y,cx,cy,charsX,charsY,fill,flags;
        public ushort show, reservedSize; public IntPtr reservedPtr, input, output, error;
    }
    [StructLayout(LayoutKind.Sequential)] struct SIX { public SI si; public IntPtr attrs; }
    [StructLayout(LayoutKind.Sequential)] struct PI { public IntPtr process, thread; public uint pid, tid; }
    [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr CreateJobObjectW(IntPtr sa, IntPtr name);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetInformationJobObject(IntPtr job, int cls, IntPtr data, uint size);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool InitializeProcThreadAttributeList(IntPtr list, int count, int flags, ref IntPtr size);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool UpdateProcThreadAttribute(IntPtr list, uint flags, IntPtr attr, IntPtr data, IntPtr size, IntPtr prev, IntPtr returned);
    [DllImport("kernel32.dll")] static extern void DeleteProcThreadAttributeList(IntPtr list);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool CreateProcessW(string exe, StringBuilder cmd, IntPtr pa, IntPtr ta, bool inherit, uint flags, IntPtr env, string cwd, ref SIX si, out PI pi);
    [DllImport("kernel32.dll")] static extern IntPtr GetStdHandle(int n);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool DuplicateHandle(IntPtr source, IntPtr handle, IntPtr target, out IntPtr copy, uint access, bool inherit, uint options);
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr handle, uint ms);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetExitCodeProcess(IntPtr process, out uint code);
    [DllImport("kernel32.dll")] static extern void GetNativeSystemInfo(IntPtr info);
    delegate bool Handler(uint type);
    [DllImport("kernel32.dll")] static extern bool SetConsoleCtrlHandler(Handler handler, bool add);
    static Handler control = delegate(uint type) { return type == 0 || type == 1; };
    static void Check(bool ok) { if (!ok) throw new Win32Exception(Marshal.GetLastWin32Error()); }
    static string Quote(string s) {
        var b = new StringBuilder("\""); int slashes = 0;
        foreach (char c in s) {
            if (c == '\\') { slashes++; continue; }
            b.Append('\\', c == '"' ? slashes * 2 + 1 : slashes); b.Append(c); slashes = 0;
        }
        return b.Append('\\', slashes * 2).Append('"').ToString();
    }
    static int Main(string[] args) {
        IntPtr job = IntPtr.Zero, attrs = IntPtr.Zero, values = IntPtr.Zero;
        FileStream active = null;
        IntPtr[] handles = new IntPtr[3]; PI pi = new PI(); bool initialized = false;
        try {
            var info = Marshal.AllocHGlobal(64);
            try { GetNativeSystemInfo(info); if (Marshal.ReadInt16(info) != 9) throw new Exception("JV CLI requires native Windows AMD64."); }
            finally { Marshal.FreeHGlobal(info); }
            Environment.SetEnvironmentVariable("PROCESSOR_ARCHITECTURE", "AMD64");
            string root = AppDomain.CurrentDomain.BaseDirectory;
            // Concurrent runtimes share this read lock. Setup holds it exclusively.
            active = new FileStream(Path.Combine(root, "use.lock"), FileMode.Open, FileAccess.Read, FileShare.Read);
            {
                job = CreateJobObjectW(IntPtr.Zero, IntPtr.Zero); Check(job != IntPtr.Zero);
                values = Marshal.AllocHGlobal(144);
                for (int i=0; i<144; i++) Marshal.WriteByte(values, i, 0);
                Marshal.WriteInt32(values, 16, 0x2000); // Extended limits: kill on last handle close.
                Check(SetInformationJobObject(job, 9, values, 144));
                IntPtr size = IntPtr.Zero;
                InitializeProcThreadAttributeList(IntPtr.Zero, 2, 0, ref size);
                attrs = Marshal.AllocHGlobal(size); Check(InitializeProcThreadAttributeList(attrs, 2, 0, ref size)); initialized = true;
                Marshal.WriteIntPtr(values, job);
                Check(UpdateProcThreadAttribute(attrs, 0, new IntPtr(0x2000d), values, new IntPtr(8), IntPtr.Zero, IntPtr.Zero));
                for (int i=0; i<3; i++) {
                    Check(DuplicateHandle(GetCurrentProcess(), GetStdHandle(-10-i), GetCurrentProcess(), out handles[i], 0, true, 2));
                    Marshal.WriteIntPtr(values, 8+i*8, handles[i]);
                }
                Check(UpdateProcThreadAttribute(attrs, 0, new IntPtr(0x20002), IntPtr.Add(values,8), new IntPtr(24), IntPtr.Zero, IntPtr.Zero));
                var si = new SIX(); si.si.cb = (uint)Marshal.SizeOf(si); si.si.flags = 0x100;
                si.si.input=handles[0]; si.si.output=handles[1]; si.si.error=handles[2]; si.attrs=attrs;
                string python = Path.Combine(root, "python", "python.exe");
                var command = new StringBuilder(Quote(python)+" -X utf8 -B "+Quote(Path.Combine(root,"bin","jvcli")));
                foreach (string arg in args) command.Append(' ').Append(Quote(arg));
                Check(SetConsoleCtrlHandler(control, true));
                Check(CreateProcessW(python, command, IntPtr.Zero, IntPtr.Zero, true, 0x80000, IntPtr.Zero, null, ref si, out pi));
                foreach (IntPtr h in handles) CloseHandle(h); Array.Clear(handles,0,3);
                if (WaitForSingleObject(pi.process, 0xffffffff) != 0) throw new Exception("JV CLI runtime wait failed.");
                uint code; Check(GetExitCodeProcess(pi.process, out code)); return unchecked((int)code);
            }
        } catch (Exception e) { Console.Error.WriteLine("JV CLI: " + e.Message); return 2; }
        finally {
            if (job != IntPtr.Zero) CloseHandle(job);
            if (pi.thread != IntPtr.Zero) CloseHandle(pi.thread);
            if (pi.process != IntPtr.Zero) CloseHandle(pi.process);
            foreach (IntPtr h in handles) if (h != IntPtr.Zero) CloseHandle(h);
            if (initialized) DeleteProcThreadAttributeList(attrs);
            if (attrs != IntPtr.Zero) Marshal.FreeHGlobal(attrs);
            if (values != IntPtr.Zero) Marshal.FreeHGlobal(values);
            if (active != null) active.Dispose();
        }
    }
}
