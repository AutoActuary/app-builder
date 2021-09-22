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
    //*******************************************
    //Get commanline string as a whole
    //*******************************************
    TCHAR* cmdArgs = GetCommandLineW();
    TCHAR* cmdPath;
    cmdPath = (TCHAR*) malloc((_tcslen(cmdArgs)+1)*2);
    cmdPath[0] = '\0';
    cmdPath[1] = '\0';

    _tcscpy(cmdPath, cmdArgs);


    //*******************************************
    //Split filepath, filename, and commandline
    //*******************************************
    bool inQuote = false;
    bool isArgs = false;
    int j = 0;

    for(int i=0; i<_tcslen(cmdArgs)+1; i++){
      //must be easier way to index unicode string
      TCHAR c = *(TCHAR *)(&cmdArgs[i*2]);
      
      if(c == L'"'){inQuote = !inQuote;}
      if(c == L' ' && !inQuote){ isArgs = true;}

      if(isArgs){
        cmdPath[i*2]   = '\0';
        cmdPath[i*2+1] = '\0';
      }

      //do for both unicode bits
      cmdArgs[j*2  ] = cmdArgs[i*2  ];
      cmdArgs[j*2+1] = cmdArgs[i*2+1];

      //sync j with i after filepath
      if(isArgs){ j++; }
    }


    //*******************************************
    //Remove quotes around filepath
    //*******************************************
    if(*(TCHAR *)(&cmdPath[0]) == L'"'){
      cmdPath = &cmdPath[2];
    }
    int cmdPathEnd = _tcslen(cmdPath);
    if(*(TCHAR *)(&cmdPath[(cmdPathEnd-1)*2]) == L'"'){
      cmdPath[(cmdPathEnd-1)*2]='\0';
      cmdPath[(cmdPathEnd-1)*2+1]='\0';
    }


    //*******************************************
    //Find basedir of cmdPath
    //*******************************************
    TCHAR* cmdBaseDir;
    cmdBaseDir = (TCHAR*) malloc((_tcslen(cmdPath)+1)*2);
    cmdBaseDir[0] = '\0';
    cmdBaseDir[1] = '\0';

    _tcscpy(cmdBaseDir, cmdPath);


    int nrOfSlashed = 0;
    int slashLoc = 0;
    for(int i=0; i<_tcslen(cmdBaseDir); i++){
      //must be easier way to index unicode string
      TCHAR c = *(TCHAR *)(&cmdBaseDir[i*2]);
      if(c == L'\\' || c == L'//'){
        nrOfSlashed+=1;
        slashLoc=i;
      }
    }

    if(nrOfSlashed==0){
      _tcscpy(cmdBaseDir, L".");
    }else{
      cmdBaseDir[2*slashLoc] = '\0';
      cmdBaseDir[2*slashLoc+1] = '\0';  
    }


    //*******************************************
    //Find filename without .exe
    //*******************************************
    TCHAR* cmdName;
    cmdName = (TCHAR*) malloc((_tcslen(cmdPath)+1)*2);
    cmdName[0] = '\0';
    cmdName[1] = '\0';

    _tcscpy(cmdName, cmdPath);

    cmdName = &cmdPath[slashLoc==0?0:slashLoc*2+2];
    int fnameend = _tcslen(cmdName);
    
    // if we run as path\program.exe then we need to truncate the .exe part
    if(0 < fnameend-4 && cmdName[(fnameend-4)*2] == '.'){
        cmdName[(fnameend-4)*2]   = '\0';
        cmdName[(fnameend-4)*2+1] = '\0';
    }


    //*******************************************
    //Get into this form: cmd.exe /c ""c:\path\...bat" arg1 arg2 ... "
    //*******************************************
    //TCHAR* cmdLine?  = L"python.exe ";
    TCHAR* cmdLine1  = L"cmd.exe /c \"";
    
    TCHAR* cmdLine2  = L"\"";
    TCHAR* cmdLine3  = cmdBaseDir;
    TCHAR* cmdLine4  = L"\\activate-julia-environment.cmd";
    TCHAR* cmdLine5  = L"\" & ";

    TCHAR* cmdLine6  = L"\"";
    TCHAR* cmdLine7  = cmdBaseDir;
    TCHAR* cmdLine8  = L"\\julia\\bin\\julia.exe";
    TCHAR* cmdLine9 = L"\" ";
    
    TCHAR* cmdLine10 = cmdArgs;
    TCHAR* cmdLine11= L"\"";

    int totlen;
    totlen = ( _tcslen(cmdLine1)+_tcslen(cmdLine2)+_tcslen(cmdLine3)+_tcslen(cmdLine4)+_tcslen(cmdLine5)+_tcslen(cmdLine6)+_tcslen(cmdLine7)+_tcslen(cmdLine8)+_tcslen(cmdLine9)+_tcslen(cmdLine10)+_tcslen(cmdLine11));

    TCHAR* cmdLine;
    cmdLine = (TCHAR*) malloc((totlen+1)*2);
    cmdLine[0] = '\0';
    cmdLine[1] = '\0';

    //Pick correct cmd sequence sequence
    _tcscat(cmdLine, cmdLine1);
    _tcscat(cmdLine, cmdLine2);
    _tcscat(cmdLine, cmdLine3);
    _tcscat(cmdLine, cmdLine4);
    _tcscat(cmdLine, cmdLine5);
    _tcscat(cmdLine, cmdLine6);
    _tcscat(cmdLine, cmdLine7);
    _tcscat(cmdLine, cmdLine8);
    _tcscat(cmdLine, cmdLine9);
    _tcscat(cmdLine, cmdLine10);
    _tcscat(cmdLine, cmdLine11);


    //************************************
    //Prepare and run CreateProcessW
    //************************************
    PROCESS_INFORMATION pi;
    STARTUPINFO si;
        
    memset(&si, 0, sizeof(si));
    si.cb = sizeof(si);

    #ifdef NOSHELL
        CreateProcessW(NULL, cmdLine, NULL, NULL, TRUE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi);
    #else
        CreateProcessW(NULL, cmdLine, NULL, NULL, TRUE, NULL,             NULL, NULL, &si, &pi);
    #endif

    //************************************
    //Return ErrorLevel
    //************************************
    DWORD result = WaitForSingleObject(pi.hProcess, INFINITE);

    if(result == WAIT_TIMEOUT){return -2;} //Timeout error

    DWORD exitCode=0;
    if(!GetExitCodeProcess(pi.hProcess, &exitCode) ){return -1;} //Cannot get exitcode

    return exitCode; //Correct exitcode
}
