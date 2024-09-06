//#define NOSHELL

#define _WIN32_WINNT 0x0500
#include <windows.h>
#include <stdbool.h>
#include <tchar.h>
#include <wctype.h>

// Function to check if a directory name matches python\-\d.\d.*
int matchPythonDir(TCHAR* dirName) {
    int len = _tcslen(dirName);

    if (len < 10) {
        return 0;
    }

    // Check if the name starts with "python-"
    if (_tcsncmp(dirName, _T("python-"), 7) != 0) {
        return 0;
    }

    // Check if the 8th character is a digit (index 7)
    if (!iswdigit(dirName[7])) {
        return 0;
    }

    // Check if the 9th character is a dot (index 8)
    if (dirName[8] != _T('.')) {
        return 0;
    }

    // Check if the 10th character is a digit (index 9)
    if (!iswdigit(dirName[9])) {
        return 0;
    }

    return 1;
}


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
      if(c == L'\\' || c == L'/'){
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
    // Now search for "python-<digit>.<digit><anything>"
    // *******************************************

    WIN32_FIND_DATAW findFileData;
    HANDLE hFind;

    // Prepare the search pattern: <exeBaseDir>\*
    //TCHAR searchPattern[MAX_PATH];
    TCHAR* searchPattern;
    searchPattern = (TCHAR*) malloc((_tcslen(exeBaseDir)+10)*2);
    _stprintf(searchPattern, _T("%s\\..\\*"), exeBaseDir);

    // Find the first file in the directory
    hFind = FindFirstFileW(searchPattern, &findFileData);
    if (hFind == INVALID_HANDLE_VALUE) {
        _ftprintf(stderr, _T("Cannot find \"%s\\python-<version>\"; GetLastError() = (%d)\n"), exeBaseDir, GetLastError());
        return 1;
    }

    do {
        if (findFileData.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY){
            if(
              _tcslen(findFileData.cFileName) > 8 
              && findFileData.cFileName[0] == L'p'
              && findFileData.cFileName[1] == L'y'
              && findFileData.cFileName[2] == L't'
              && findFileData.cFileName[3] == L'h'
              && findFileData.cFileName[4] == L'o'
              && findFileData.cFileName[5] == L'n'
              && findFileData.cFileName[6] == L'-'
              && findFileData.cFileName[7] == L'3'
              && findFileData.cFileName[8] == L'.'
            ){
                goto found_python_dir;
            }
        }
    } while (FindNextFileW(hFind, &findFileData) != 0);

    _ftprintf(stderr, _T("Cannot find \"%s\\python-<version>\"\n"), exeBaseDir);
    return 1;

    found_python_dir:
    FindClose(hFind);

    // *******************************************
    // Get into this form: "c:\path\to\python.exe" "c:\path\to\<progName>.zip" <args...>
    // *******************************************
    TCHAR* cmdLine1 = L"\"";
    TCHAR* cmdLine2 = exeBaseDir;
    TCHAR* cmdLine3 = L"\\..\\";
    TCHAR* cmdLine4 = findFileData.cFileName;
    TCHAR* cmdLine5 = L"\\python.exe\" ";
    TCHAR* cmdLine6 = cmdArgs;

    totlen = (_tcslen(cmdLine1)+_tcslen(cmdLine2)+_tcslen(cmdLine3)+_tcslen(cmdLine4)+_tcslen(cmdLine5)+_tcslen(cmdLine6));

    TCHAR* cmdLine;
    cmdLine = (TCHAR*) malloc((totlen+3)*2);
    cmdLine[0] = '\0';
    cmdLine[1] = '\0';

    //Pick correct cmd sequence sequence
    _tcscat(cmdLine, cmdLine1);
    _tcscat(cmdLine, cmdLine2);
    _tcscat(cmdLine, cmdLine3);
    _tcscat(cmdLine, cmdLine4);
    _tcscat(cmdLine, cmdLine5);
    _tcscat(cmdLine, cmdLine6);

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

