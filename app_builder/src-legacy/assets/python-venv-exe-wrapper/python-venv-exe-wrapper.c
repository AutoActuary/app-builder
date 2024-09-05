//#define NOSHELL

#define _WIN32_WINNT 0x0500
#include <windows.h>
#include <stdbool.h>
#include <tchar.h>

#ifdef NOSHELL
    int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow)
#else
    int main( int argc, char ** argv ) 
#endif
{
    // *******************************************
    //Get a direct path to the current running exe
    // *******************************************
    int size = 125;
    TCHAR* cmdPath = (TCHAR*)malloc(1);

    // read until GetModuleFileNameW writes less than its cap (of size)
    do {
        size *= 2;
        free(cmdPath);
        cmdPath = (TCHAR*)malloc(size*2);

    } while (GetModuleFileNameW(NULL, cmdPath, size) == size);


    // *******************************************
    // Get commandline string as a whole
    // *******************************************
    TCHAR* cmdArgs = GetCommandLineW();

    // *******************************************
    // Remove argument 0 from the commandline string
    // http://www.windowsinspired.com/how-a-windows-programs-splits-its-command-line-into-individual-arguments/
    // *******************************************
    bool inQuote = false;
    bool isArgs = false;
    int j = 0;

    for(int i=0; i<_tcslen(cmdArgs)+1; i++){
      //must be easier way to index unicode string
      TCHAR c = *(TCHAR *)(&cmdArgs[i*2]);
      
      if(c == L'"'){inQuote = !inQuote;}
      if(c == L' ' && !inQuote){ isArgs = true;}

      //do for both unicode bits
      cmdArgs[j*2  ] = cmdArgs[i*2  ];
      cmdArgs[j*2+1] = cmdArgs[i*2+1];

      //sync j with i after filepath
      if(isArgs){ j++; }
    }


    // *******************************************
    // Find basedir of cmdPath
    // *******************************************
    TCHAR* exeBaseDir;
    exeBaseDir = (TCHAR*) malloc((_tcslen(cmdPath)+1)*2);
    exeBaseDir[0] = '\0';
    exeBaseDir[1] = '\0';

    _tcscpy(exeBaseDir, cmdPath);


    int nrOfSlashed = 0;
    int slashLoc = 0;
    for(int i=0; i<_tcslen(exeBaseDir); i++){
      //must be easier way to index unicode string
      TCHAR c = *(TCHAR *)(&exeBaseDir[i*2]);
      if(c == L'\\' || c == L'//'){
        nrOfSlashed+=1;
        slashLoc=i;
      }
    }

    if(nrOfSlashed==0){
      _tcscpy(exeBaseDir, L".");
    }else{
      exeBaseDir[2*slashLoc] = '\0';
      exeBaseDir[2*slashLoc+1] = '\0';  
    }


    // *******************************************
    // Find filename without .exe
    // *******************************************
    TCHAR* progName;
    progName = (TCHAR*) malloc((_tcslen(cmdPath)+1)*2);
    progName[0] = '\0';
    progName[1] = '\0';

    _tcscpy(progName, cmdPath);

    progName = &cmdPath[slashLoc==0?0:slashLoc*2+2];
    int fnameend = _tcslen(progName);
    
    // if we run as path\program.exe then we need to truncate the .exe part
    if(0 < fnameend-4 &&  progName[(fnameend-4)*2] == '.' && 
                         (progName[(fnameend-3)*2] == 'e' || progName[(fnameend-3)*2] == 'E') &&
                         (progName[(fnameend-2)*2] == 'x' || progName[(fnameend-2)*2] == 'X') &&
                         (progName[(fnameend-1)*2] == 'e' || progName[(fnameend-1)*2] == 'E') ){
        progName[(fnameend-4)*2]   = '\0';
        progName[(fnameend-4)*2+1] = '\0';
    }

    //_tprintf(progName);
    //_tprintf(L"\n");

    int totlen;


    // *******************************************
    // Get into this form: "c:\path\...\python\python.exe" "c:\path\...\python\Scripts\<name>.exe" arg1 ...
    // *******************************************
    TCHAR* cmdLine1  = L"\"";
    TCHAR* cmdLine2  = exeBaseDir;
    TCHAR* cmdLine3  = L"\\Bin\\python.exe\" ";
    TCHAR* cmdLine4  = cmdArgs;

    totlen = (_tcslen(cmdLine1)+_tcslen(cmdLine2)+_tcslen(cmdLine3)+_tcslen(cmdLine4));

    TCHAR* cmdLine;
    cmdLine = (TCHAR*) malloc((totlen+3)*2);
    cmdLine[0] = '\0';
    cmdLine[1] = '\0';

    //Pick correct cmd sequence sequence
    _tcscat(cmdLine, cmdLine1);
    _tcscat(cmdLine, cmdLine2);
    _tcscat(cmdLine, cmdLine3);
    _tcscat(cmdLine, cmdLine4);
    
    //_tprintf(cmdLine);
    //_tprintf(L"\n");

    // ************************************
    // Prepare and run CreateProcessW
    // ************************************
    PROCESS_INFORMATION pi;
    STARTUPINFO si;
        
    memset(&si, 0, sizeof(si));
    si.cb = sizeof(si);

    #ifdef NOSHELL
        CreateProcessW(NULL, cmdLine, NULL, NULL, TRUE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi);
    #else
        CreateProcessW(NULL, cmdLine, NULL, NULL, TRUE, NULL,             NULL, NULL, &si, &pi);
    #endif

    // ************************************
    // Return ErrorLevel
    // ************************************
    DWORD result = WaitForSingleObject(pi.hProcess, INFINITE);

    if(result == WAIT_TIMEOUT){return -2;} //Timeout error

    DWORD exitCode=0;
    if(!GetExitCodeProcess(pi.hProcess, &exitCode) ){return -1;} //Cannot get exitcode

    return exitCode; //Correct exitcode
}

