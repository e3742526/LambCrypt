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

#include "System.h"
#include <wx/stackwalk.h>

#include "Main.h"
#include "Application.h"
#include "UserInterface.h"
#include "GraphicUserInterface.h"

#ifdef TC_UNIX
#include <signal.h>
#endif

#include "FatalErrorHandler.h"

namespace VeraCrypt
{
	static terminate_handler DefaultTerminateHandler;

#ifdef TC_UNIX
	static void OnFatalProgramErrorSignal (int, siginfo_t *, void *)
	{
		if (Gui->AskYesNo (L"LambCrypt encountered a fatal error. Open the issue tracker?", true))
			wxLaunchDefaultBrowser (Gui->GetHomepageLinkURL (L"err-report"), wxBROWSER_NEW_WINDOW);

		_exit (1);
	}
#endif // TC_UNIX

	void FatalErrorHandler::Deregister()
	{
#ifdef TC_UNIX
		signal (SIGILL, SIG_DFL);
		signal (SIGFPE, SIG_DFL);
		signal (SIGSEGV, SIG_DFL);
		signal (SIGBUS, SIG_DFL);
		signal (SIGSYS, SIG_DFL);
#endif

#ifndef TC_WINDOWS
		std::set_terminate (DefaultTerminateHandler);
#endif
	}

	void FatalErrorHandler::OnTerminate ()
	{
		try
		{
			throw;
		}
		catch (UserAbort&)
		{
		}
		catch (const Exception &)
		{
			if (Gui->AskYesNo (L"LambCrypt encountered an unhandled exception. Open the issue tracker?", true))
				wxLaunchDefaultBrowser (Gui->GetHomepageLinkURL (L"err-report"), wxBROWSER_NEW_WINDOW);
		}
		catch (exception &e)
		{
			Gui->ShowError (e);
		}
		catch (...)
		{
			Gui->ShowError (LangString["LINUX_UNKNOWN_EXC_OCCURRED"]);
		}

		_exit (1);
	}

	void FatalErrorHandler::Register ()
	{
#ifndef TC_WINDOWS
		 // OnUnhandledException() seems to be called only on Windows
		DefaultTerminateHandler = std::set_terminate (OnTerminate);
#endif

#ifdef TC_UNIX
		struct sigaction action;
		Memory::Zero (&action, sizeof (action));
		action.sa_flags = SA_SIGINFO;
		action.sa_sigaction = OnFatalProgramErrorSignal;

		throw_sys_if (sigaction (SIGILL, &action, nullptr) == -1);
		throw_sys_if (sigaction (SIGFPE, &action, nullptr) == -1);
		throw_sys_if (sigaction (SIGSEGV, &action, nullptr) == -1);
		throw_sys_if (sigaction (SIGBUS, &action, nullptr) == -1);
		throw_sys_if (sigaction (SIGSYS, &action, nullptr) == -1);
#endif
	}
}
