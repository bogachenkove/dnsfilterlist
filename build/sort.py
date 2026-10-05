#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import mmap
import os
import sys
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

scriptDirectory = Path(__file__).resolve().parent
rootDirectory = scriptDirectory.parent
inputFilePath = rootDirectory / "bogachenkoDNSFL.txt"

pipeCharacter = 0x7C
caretCharacter = 0x5E
slashCharacter = 0x2F
dollarCharacter = 0x24
starCharacter = 0x2A
questionCharacter = 0x3F
backslashCharacter = 0x5C
hashCharacter = 0x23
spaceCharacter = 0x20
tabCharacter = 0x09
lineFeedCharacter = 0x0A
carriageReturnCharacter = 0x0D
verticalTabCharacter = 0x0B
formFeedCharacter = 0x0C
leftBracketCharacter = 0x5B
rightBracketCharacter = 0x5D

whitespaceLookup = bytearray(256)
whitespaceLookup[spaceCharacter] = 1
whitespaceLookup[tabCharacter] = 1
whitespaceLookup[lineFeedCharacter] = 1
whitespaceLookup[verticalTabCharacter] = 1
whitespaceLookup[formFeedCharacter] = 1
whitespaceLookup[carriageReturnCharacter] = 1

invalidDomainLookup = bytearray(256)
invalidDomainLookup[slashCharacter] = 1
invalidDomainLookup[backslashCharacter] = 1
invalidDomainLookup[caretCharacter] = 1
invalidDomainLookup[starCharacter] = 1
invalidDomainLookup[questionCharacter] = 1

denyallowTag = b"$denyallow="
denyallowTagLength = 11
pipeBytes = b"|"
newlineBytes = b"\n"
emptyBytes = b""
temporaryFileSuffix = ".sorting"
batchSize = 1 << 16

regexKind = 0
domainKind = 1
otherKind = 2


class mappedFile:
    __slots__ = ("fileDescriptor", "memoryMap", "fileSize")

    def __init__(self, filePath: Path) -> None:
        self.fileDescriptor = os.open(str(filePath), os.O_RDONLY)
        self.memoryMap: Optional[mmap.mmap] = None
        try:
            self.fileSize = os.fstat(self.fileDescriptor).st_size
            if self.fileSize:
                self.memoryMap = mmap.mmap(self.fileDescriptor, 0, access=mmap.ACCESS_READ)
        except BaseException:
            os.close(self.fileDescriptor)
            self.fileDescriptor = -1
            raise

    def getMap(self) -> Optional[mmap.mmap]:
        return self.memoryMap

    def close(self) -> None:
        currentMap = self.memoryMap
        self.memoryMap = None
        if currentMap is not None:
            currentMap.close()
        currentDescriptor = self.fileDescriptor
        self.fileDescriptor = -1
        if currentDescriptor >= 0:
            os.close(currentDescriptor)

    def __enter__(self) -> "mappedFile":
        return self

    def __exit__(self, excType: object, excValue: object, traceback: object) -> None:
        self.close()


class section:
    __slots__ = ("headerText", "sortKey", "ruleBoundaries", "ruleKind")

    def __init__(
        self,
        headerText: bytes,
        sortKey: bytes,
        ruleBoundaries: List[Tuple[int, int]],
        ruleKind: int,
    ) -> None:
        self.headerText = headerText
        self.sortKey = sortKey
        self.ruleBoundaries = ruleBoundaries
        self.ruleKind = ruleKind


def stripBoundaries(memoryMap: mmap.mmap, startIndex: int, endIndex: int) -> Tuple[int, int]:
    lookupTable = whitespaceLookup
    while endIndex > startIndex and lookupTable[memoryMap[endIndex - 1]]:
        endIndex -= 1
    while startIndex < endIndex and lookupTable[memoryMap[startIndex]]:
        startIndex += 1
    return startIndex, endIndex


def extractSectionInner(memoryMap: mmap.mmap, startIndex: int, endIndex: int) -> Optional[Tuple[int, int]]:
    startIndex, endIndex = stripBoundaries(memoryMap, startIndex, endIndex)
    if endIndex - startIndex < 3:
        return None
    if memoryMap[startIndex] != hashCharacter:
        return None
    
    lookupTable = whitespaceLookup
    characterIndex = startIndex + 1
    while characterIndex < endIndex and lookupTable[memoryMap[characterIndex]]:
        characterIndex += 1
        
    if characterIndex >= endIndex or memoryMap[characterIndex] != leftBracketCharacter:
        return None
    if memoryMap[endIndex - 1] != rightBracketCharacter:
        return None
        
    innerStart = characterIndex + 1
    innerEnd = endIndex - 1
    while innerEnd > innerStart and lookupTable[memoryMap[innerEnd - 1]]:
        innerEnd -= 1
    while innerStart < innerEnd and lookupTable[memoryMap[innerStart]]:
        innerStart += 1
    return innerStart, innerEnd


def extractDomainInner(memoryMap: mmap.mmap, startIndex: int, endIndex: int) -> Optional[Tuple[int, int]]:
    if endIndex - startIndex < 3:
        return None
    if memoryMap[startIndex] != pipeCharacter or memoryMap[startIndex + 1] != pipeCharacter:
        return None
        
    domainStart = startIndex + 2
    domainEnd = endIndex
    
    characterIndex = domainStart
    while characterIndex < endIndex:
        currentCharacter = memoryMap[characterIndex]
        if currentCharacter == caretCharacter or currentCharacter == dollarCharacter:
            domainEnd = characterIndex
            break
        characterIndex += 1
        
    if domainEnd <= domainStart:
        return None
        
    invalidTable = invalidDomainLookup
    characterIndex = domainStart
    while characterIndex < domainEnd:
        if invalidTable[memoryMap[characterIndex]]:
            return None
        characterIndex += 1
    return domainStart, domainEnd


def findDenyallowPayload(memoryMap: mmap.mmap, startIndex: int, endIndex: int) -> Optional[Tuple[int, int]]:
    searchPosition = memoryMap.find(denyallowTag, startIndex, endIndex)
    if searchPosition < 0:
        return None
    payloadStart = searchPosition + denyallowTagLength
    if payloadStart >= endIndex:
        return None
        
    lookupTable = whitespaceLookup
    payloadEnd = payloadStart
    while payloadEnd < endIndex:
        currentCharacter = memoryMap[payloadEnd]
        if lookupTable[currentCharacter] or currentCharacter == dollarCharacter:
            break
        payloadEnd += 1
        
    if payloadEnd == payloadStart:
        return None
    return payloadStart, payloadEnd


def normalizeDenyallowPayload(memoryMap: mmap.mmap, startIndex: int, endIndex: int) -> bytes:
    payloadBoundaries = findDenyallowPayload(memoryMap, startIndex, endIndex)
    if payloadBoundaries is None:
        return memoryMap[startIndex:endIndex]
        
    payloadStart, payloadEnd = payloadBoundaries
    payloadContent = memoryMap[payloadStart:payloadEnd]
    validParts = []
    addPart = validParts.append
    
    for currentPart in payloadContent.split(pipeBytes):
        cleanPart = currentPart.strip()
        if cleanPart:
            addPart(cleanPart)
            
    if len(validParts) < 2:
        return memoryMap[startIndex:endIndex]
        
    validParts.sort(key=bytes.lower)
    return memoryMap[startIndex:payloadStart] + pipeBytes.join(validParts) + memoryMap[payloadEnd:endIndex]


def generateRuleKey(memoryMap: mmap.mmap, startIndex: int, endIndex: int) -> bytes:
    innerBoundaries = extractSectionInner(memoryMap, startIndex, endIndex)
    if innerBoundaries is not None:
        rangeStart, rangeEnd = innerBoundaries
        return memoryMap[rangeStart:rangeEnd].lower()
        
    innerBoundaries = extractDomainInner(memoryMap, startIndex, endIndex)
    if innerBoundaries is not None:
        rangeStart, rangeEnd = innerBoundaries
        return memoryMap[rangeStart:rangeEnd].lower()
        
    rangeStart, rangeEnd = stripBoundaries(memoryMap, startIndex, endIndex)
    return memoryMap[rangeStart:rangeEnd].lower()


def classifySectionRules(memoryMap: mmap.mmap, ruleBoundaries: List[Tuple[int, int]]) -> int:
    ruleKind = -1
    for ruleStart, ruleEnd in ruleBoundaries:
        firstCharacter = memoryMap[ruleStart]
        if firstCharacter == hashCharacter:
            continue
        if firstCharacter == slashCharacter:
            currentKind = regexKind
        elif firstCharacter == pipeCharacter:
            currentKind = domainKind
        else:
            return otherKind
            
        if ruleKind == -1:
            ruleKind = currentKind
        elif ruleKind != currentKind:
            return otherKind
            
    return otherKind if ruleKind == -1 else ruleKind


def parseFileSections(memoryMap: mmap.mmap, fileSize: int) -> Tuple[List[Tuple[int, int]], List[section]]:
    headerBoundaries: List[Tuple[int, int]] = []
    sectionCollection: List[section] = []
    
    currentHeader: bytes = emptyBytes
    currentKey: bytes = emptyBytes
    currentBody: List[Tuple[int, int]] = []
    sectionExists = False
    
    addRuleBoundary = currentBody.append
    findNewline = memoryMap.find
    
    currentPosition = 0
    while currentPosition < fileSize:
        newlinePosition = findNewline(newlineBytes, currentPosition, fileSize)
        if newlinePosition < 0:
            newlinePosition = fileSize
            
        sectionBoundaries = extractSectionInner(memoryMap, currentPosition, newlinePosition)
        if sectionBoundaries is not None:
            if sectionExists:
                sectionCollection.append(
                    section(
                        currentHeader,
                        currentKey,
                        currentBody,
                        classifySectionRules(memoryMap, currentBody),
                    )
                )
            headerStart, headerEnd = stripBoundaries(memoryMap, currentPosition, newlinePosition)
            innerStart, innerEnd = sectionBoundaries
            currentHeader = memoryMap[headerStart:headerEnd]
            currentKey = memoryMap[innerStart:innerEnd].lower()
            currentBody = []
            addRuleBoundary = currentBody.append
            sectionExists = True
        elif not sectionExists:
            headerStart, headerEnd = stripBoundaries(memoryMap, currentPosition, newlinePosition)
            if headerEnd > headerStart:
                headerBoundaries.append((headerStart, headerEnd))
        else:
            headerStart, headerEnd = stripBoundaries(memoryMap, currentPosition, newlinePosition)
            if headerEnd > headerStart:
                addRuleBoundary((headerStart, headerEnd))
                
        currentPosition = newlinePosition + 1
        
    if sectionExists:
        sectionCollection.append(
            section(
                currentHeader,
                currentKey,
                currentBody,
                classifySectionRules(memoryMap, currentBody),
            )
        )
        
    return headerBoundaries, sectionCollection


def generateSectionSortKey(sectionEntity: section) -> Tuple[int, bytes]:
    return (sectionEntity.ruleKind, sectionEntity.sortKey)


def prepareOutputSections(memoryMap: mmap.mmap, sectionCollection: List[section]) -> None:
    sectionCollection.sort(key=generateSectionSortKey)

    def generateRuleSortKey(ruleBoundary: Tuple[int, int]) -> bytes:
        return generateRuleKey(memoryMap, ruleBoundary[0], ruleBoundary[1])

    for sectionEntity in sectionCollection:
        sectionEntity.ruleBoundaries.sort(key=generateRuleSortKey)


def iterateOutputChunks(
    memoryMap: mmap.mmap,
    headerBoundaries: List[Tuple[int, int]],
    sectionCollection: List[section],
) -> Iterator[bytes]:
    contentWritten = False
    for chunkStart, chunkEnd in headerBoundaries:
        yield memoryMap[chunkStart:chunkEnd]
        contentWritten = True
        
    for sectionEntity in sectionCollection:
        if contentWritten:
            yield emptyBytes
        yield sectionEntity.headerText
        contentWritten = True
        
        for ruleStart, ruleEnd in sectionEntity.ruleBoundaries:
            yield normalizeDenyallowPayload(memoryMap, ruleStart, ruleEnd)
        contentWritten = True


def writeTemporaryFile(targetPath: Path, outputChunks: Iterator[bytes]) -> Path:
    temporaryPath = targetPath.with_name(targetPath.name + temporaryFileSuffix)
    fileDescriptor = -1
    try:
        fileDescriptor = os.open(str(temporaryPath), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        writeBuffer = bytearray(batchSize)
        bufferView = memoryview(writeBuffer)
        occupiedSpace = 0
        bufferLimit = batchSize
        
        try:
            for currentChunk in outputChunks:
                chunkLength = len(currentChunk)
                if occupiedSpace + chunkLength + 1 > bufferLimit:
                    if occupiedSpace:
                        os.write(fileDescriptor, bufferView[:occupiedSpace])
                    occupiedSpace = 0
                if chunkLength + 1 > bufferLimit:
                    os.write(fileDescriptor, currentChunk)
                    os.write(fileDescriptor, newlineBytes)
                    continue
                    
                writeBuffer[occupiedSpace:occupiedSpace + chunkLength] = currentChunk
                occupiedSpace += chunkLength
                writeBuffer[occupiedSpace] = lineFeedCharacter
                occupiedSpace += 1
                
            if occupiedSpace:
                os.write(fileDescriptor, bufferView[:occupiedSpace])
            os.fsync(fileDescriptor)
        finally:
            bufferView.release()
            os.close(fileDescriptor)
            fileDescriptor = -1
            
        return temporaryPath
    except BaseException:
        if fileDescriptor >= 0:
            os.close(fileDescriptor)
        try:
            os.unlink(str(temporaryPath))
        except OSError:
            pass
        raise


def commitTemporaryFile(targetPath: Path, temporaryPath: Path) -> None:
    try:
        os.replace(str(temporaryPath), str(targetPath))
    except BaseException:
        try:
            os.unlink(str(temporaryPath))
        except OSError:
            pass
        raise


def main() -> int:
    if not inputFilePath.is_file():
        print(f"Error: The file '{inputFilePath}' was not found.")
        print("Make sure 'bogachenkoDNSFL.txt' is in the project root.")
        return 1
        
    temporaryPath: Optional[Path] = None
    try:
        # FIX: Windows блокирует mmap-файлы. Мы должны закрыть mmap ПЕРЕД заменой файла.
        with mappedFile(inputFilePath) as mappedFileInstance:
            memoryMap = mappedFileInstance.getMap()
            if memoryMap is None:
                temporaryPath = writeTemporaryFile(inputFilePath, iter(()))
            else:
                headerBoundaries, sectionCollection = parseFileSections(memoryMap, mappedFileInstance.fileSize)
                prepareOutputSections(memoryMap, sectionCollection)
                temporaryPath = writeTemporaryFile(inputFilePath, iterateOutputChunks(memoryMap, headerBoundaries, sectionCollection))
        
        # Блок 'with' завершился, mmap закрыт, файл разблокирован. Теперь можно безопасно заменять.
        if temporaryPath is not None:
            commitTemporaryFile(inputFilePath, temporaryPath)
            temporaryPath = None
            
    except OSError as exc:
        print(f"Error: {exc}")
        if temporaryPath is not None:
            try:
                os.unlink(str(temporaryPath))
            except OSError:
                pass
        return -1
        
    print(f"Done. Sorted in place: {inputFilePath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())