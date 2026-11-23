/*
 Derived from source code of TrueCrypt 7.1a, which is
 Copyright (c) 2008-2012 TrueCrypt Developers Association and which is governed
 by the TrueCrypt License 3.0.

 Modifications and additions to the original source code (contained in this file)
 and all other portions of this file are Copyright (c) 2013-2026 AM Crypto
 and are governed by the Apache License 2.0 the full text of which is
 contained in the file License.txt included in VeraCrypt binary and source
 code distribution packages.
*/

#ifndef TC_HEADER_Platform_Unix_Process
#define TC_HEADER_Platform_Unix_Process

#include "Platform/PlatformBase.h"
#include "Platform/Buffer.h"
#include "Platform/Functor.h"

namespace VeraCrypt
{
	struct ProcessExecFunctor
	{
		virtual ~ProcessExecFunctor () { }
		virtual void operator() (int argc, char *argv[]) = 0;
	};

	class Process
	{
	public:
		Process ();
		virtual ~Process ();

		// Best-effort protection for service processes that handle credentials or keys.
		static void DisableCoreDumps ();
		static bool IsExecutable(const std::string& path);
		// Resolves a program name against fixed system directories. By default only
		// candidates whose whole path is root-owned and not group/world-writable are
		// accepted, because results are executed with elevated privileges or are
		// given the administrator password.
		static std::string FindSystemBinary(const char* name, std::string& errorMsg, bool requireTrustedPath = true);
		// For unprivileged desktop helpers (terminals, file managers) only.
		static std::string FindUserBinary(const char* name, std::string& errorMsg);
		static string Execute (const string &processName, const list <string> &arguments, int timeOut = -1, ProcessExecFunctor *execFunctor = nullptr, const Buffer *inputData = nullptr);
#ifdef TC_MACOSX
		static uint64 GetProcessStartTime (pid_t processId);
		static bool IsProcessRunning (pid_t processId, uint64 expectedStartTime = 0);
		// A deadline aborts the child. An operation it requested from the OS may remain pending.
		static string ExecuteBounded (const string &processName, const list <string> &arguments, int timeOut, size_t outputLimit = 16 * 1024 * 1024);
		// Reports whether the child started without a confirmed normal exit and complete output.
		static string ExecuteBounded (const string &processName, const list <string> &arguments, int timeOut,
			bool &completionUnconfirmed, size_t outputLimit = 16 * 1024 * 1024);
#endif
#if defined(TC_LINUX)
		static bool IsRunningUnderAppImage (const string &executablePath);
#endif

	protected:

	private:
		Process (const Process &);
		Process &operator= (const Process &);
	};
}

#endif // TC_HEADER_Platform_Unix_Process
