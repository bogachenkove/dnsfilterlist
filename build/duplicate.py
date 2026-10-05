#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
from array import array
from contextlib import contextmanager
from mmap import ACCESS_READ, mmap
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

scriptDirectory = Path(__file__).resolve().parent
rootDirectory = scriptDirectory.parent
inputFilePath = rootDirectory / "bogachenkoDNSFL.txt"

pipeCharacter = 0x7C
caretCharacter = 0x5E
dollarCharacter = 0x24
newlineBytes = b"\n"
emptyBytes = b""  # FIX: Добавлена недостающая константа пустых байтов

invalidCharacterLookup = bytearray(256)
invalidCharacterLookup[0x2F] = 1
invalidCharacterLookup[0x5C] = 1
invalidCharacterLookup[caretCharacter] = 1
invalidCharacterLookup[0x2A] = 1
invalidCharacterLookup[0x3F] = 1

whitespaceLookup = bytearray(256)
whitespaceLookup[0x20] = 1
whitespaceLookup[0x09] = 1
whitespaceLookup[0x0A] = 1
whitespaceLookup[0x0B] = 1
whitespaceLookup[0x0C] = 1
whitespaceLookup[0x0D] = 1

arrayPackCode = "Q"
reportHeader = "=== Searching for Duplicate Domains ==="
cleanMessage = "No duplicates found. Your list is clean!"


@contextmanager
def openMemoryMap(filePath: Path) -> Iterator[Optional[mmap]]:
    fileDescriptor = os.open(filePath, os.O_RDONLY)
    try:
        if os.fstat(fileDescriptor).st_size == 0:
            yield None
            return
        memoryMap = mmap(fileDescriptor, 0, access=ACCESS_READ)
        try:
            yield memoryMap
        finally:
            memoryMap.close()
    finally:
        os.close(fileDescriptor)


class duplicateFinder:
    __slots__ = ("targetPath", "domainIndex")

    def __init__(self, filePath: Path) -> None:
        self.targetPath = filePath
        self.domainIndex: dict[bytes, array] = {}

    def buildDomainIndex(self) -> None:
        domainIndex = self.domainIndex
        indexGet = domainIndex.get
        invalidTable = invalidCharacterLookup
        whitespaceTable = whitespaceLookup
        
        with openMemoryMap(self.targetPath) as memoryMap:
            if memoryMap is None:
                return
            memoryView = memoryview(memoryMap)
            try:
                findNewline = memoryMap.find
                memorySize = len(memoryView)
                currentPosition = 0
                lineNumber = 0
                
                while currentPosition < memorySize:
                    newlinePosition = findNewline(newlineBytes, currentPosition)
                    if newlinePosition < 0:
                        newlinePosition = memorySize
                    lineNumber += 1
                    
                    lineStart = currentPosition
                    lineEnd = newlinePosition
                    
                    while lineEnd > lineStart and whitespaceTable[memoryView[lineEnd - 1]]:
                        lineEnd -= 1
                    while lineStart < lineEnd and whitespaceTable[memoryView[lineStart]]:
                        lineStart += 1
                        
                    if lineEnd - lineStart >= 3 and memoryView[lineStart] == pipeCharacter and memoryView[lineStart + 1] == pipeCharacter:
                        domainEnd = lineEnd
                        characterIndex = lineStart + 2
                        
                        while characterIndex < lineEnd:
                            currentCharacter = memoryView[characterIndex]
                            if currentCharacter == caretCharacter or currentCharacter == dollarCharacter:
                                domainEnd = characterIndex
                                break
                            characterIndex += 1
                            
                        if domainEnd - lineStart > 2:
                            characterIndex = lineStart + 2
                            while characterIndex < domainEnd and not invalidTable[memoryView[characterIndex]]:
                                characterIndex += 1
                                
                            if characterIndex == domainEnd:
                                rawDomain = bytes(memoryView[lineStart + 2:domainEnd])
                                domainKey = rawDomain if rawDomain.islower() else rawDomain.lower()
                                
                                lineNumberList = indexGet(domainKey)
                                if lineNumberList is None:
                                    lineNumberList = array(arrayPackCode)
                                    lineNumberList.append(lineNumber)
                                    domainIndex[domainKey] = lineNumberList
                                else:
                                    lineNumberList.append(lineNumber)
                    currentPosition = newlinePosition + 1
            finally:
                memoryView.release()

    def iterateDuplicates(self) -> Iterator[Tuple[bytes, array]]:
        for domainKey, lineNumberList in self.domainIndex.items():
            if len(lineNumberList) > 1:
                yield domainKey, lineNumberList

    def clearIndex(self) -> None:
        self.domainIndex.clear()


def generateDuplicateReport(filePath: Path) -> int:
    duplicateFinderInstance = duplicateFinder(filePath)
    duplicateFinderInstance.buildDomainIndex()
    
    duplicateEntries: List[Tuple[bytes, array]] = []
    for currentEntry in duplicateFinderInstance.iterateDuplicates():
        duplicateEntries.append(currentEntry)
        
    print(reportHeader)
    if not duplicateEntries:
        duplicateFinderInstance.clearIndex()
        print(cleanMessage)
        return 0
        
    neededLineNumbers: set[int] = set()
    for _, lineNumberList in duplicateEntries:
        neededLineNumbers.update(lineNumberList)
        
    lineContentMap: dict[int, bytes] = {}
    try:
        with openMemoryMap(filePath) as memoryMap:
            if memoryMap is not None:
                memoryView = memoryview(memoryMap)
                try:
                    findNewline = memoryMap.find
                    memorySize = len(memoryView)
                    whitespaceTable = whitespaceLookup
                    currentPosition = 0
                    lineNumber = 0
                    remainingLines = len(neededLineNumbers)
                    
                    while currentPosition < memorySize and remainingLines:
                        newlinePosition = findNewline(newlineBytes, currentPosition)
                        if newlinePosition < 0:
                            newlinePosition = memorySize
                        lineNumber += 1
                        
                        if lineNumber in neededLineNumbers:
                            lineStart = currentPosition
                            lineEnd = newlinePosition
                            while lineEnd > lineStart and whitespaceTable[memoryView[lineEnd - 1]]:
                                lineEnd -= 1
                            while lineStart < lineEnd and whitespaceTable[memoryView[lineStart]]:
                                lineStart += 1
                            lineContentMap[lineNumber] = bytes(memoryView[lineStart:lineEnd])
                            remainingLines -= 1
                        currentPosition = newlinePosition + 1
                finally:
                    memoryView.release()
                    
        for domainKey, lineNumberList in duplicateEntries:
            lineNumberText = ", ".join(str(currentLineNumber) for currentLineNumber in lineNumberList)
            asciiDomainKey = domainKey.decode("ascii", "replace")
            print(f"Domain [ {asciiDomainKey} ] found {len(lineNumberList)} times (lines: {lineNumberText})")
            
            for currentLineNumber in lineNumberList:
                # FIX: emptyBytes теперь корректно определен в глобальных константах
                asciiLineContent = lineContentMap.get(currentLineNumber, emptyBytes).decode("utf-8", "replace")
                print(f"    line {currentLineNumber}: {asciiLineContent}")
    finally:
        lineContentMap.clear()
        neededLineNumbers.clear()
        duplicateEntries.clear()
        duplicateFinderInstance.clearIndex()
        
    return 0


def main() -> int:
    if not inputFilePath.is_file():
        print(f"Error: The file '{inputFilePath}' was not found.")
        print("Make sure 'bogachenkoDNSFL.txt' is in the project root.")
        return 1
    return generateDuplicateReport(inputFilePath)


if __name__ == "__main__":
    sys.exit(main())