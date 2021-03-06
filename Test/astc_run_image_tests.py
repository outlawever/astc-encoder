#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# -----------------------------------------------------------------------------
# Copyright 2019-2020 Arm Limited
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at:
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
# -----------------------------------------------------------------------------
"""
Main script for running image testing from the command line.

Attributes:
    RESULT_THRESHOLD_WARN: The result threshold (dB) for getting a WARN.
    RESULT_THRESHOLD_FAIL: The result threshold (dB) for getting a FAIL.
    TEST_BLOCK_SIZES: The block sizes we can test. This is a subset of the
        block sizes supported by ASTC, simply to keep test run times
        manageable.
"""

import argparse
import os
import sys

import testlib.encoder as te
import testlib.testset as tts
import testlib.resultset as trs


RESULT_THRESHOLD_WARN = -0.1

RESULT_THRESHOLD_FAIL = -0.2

RESULT_THRESHOLD_3D_FAIL = -0.6

TEST_BLOCK_SIZES = ["4x4", "5x5", "6x6", "8x8", "12x12",
                    "3x3x3", "6x6x6"]


def is_3d(blockSize):
    """
    Is a block size string for a 3D block?

    Return:
        True if the block string is a 3D block size.
    """
    return blockSize.count("x") == 2


def count_test_set(testSet, blockSizes):
    """
    Count the number of test executions needed for a test set.

    Args:
        testSet: The test set to run.
        blockSizes: The block size list to run.
    """
    count = 0
    for blkSz in blockSizes:
        for image in testSet.tests:
            # 3D block sizes require 3D images
            if is_3d(blkSz) != image.is3D:
                continue

            count += 1

    return count


def determine_result(image, reference, result):
    """
    Determine a test result against a reference and thresholds.

    Args:
        image: The image being compressed.
        reference: The reference result to compare against.
        result: The test result.

    Return:
        A Result enum.
    """
    dPSNR = result.psnr - reference.psnr

    if (dPSNR < RESULT_THRESHOLD_FAIL) and (not image.is3D):
        return trs.Result.FAIL

    if (dPSNR < RESULT_THRESHOLD_3D_FAIL) and image.is3D:
        return trs.Result.FAIL

    if dPSNR < RESULT_THRESHOLD_WARN:
        return trs.Result.WARN

    return trs.Result.PASS


def format_solo_result(image, result):
    """
    Format a metrics string for a single (no compare) result.

    Args:
        image: The image being tested.
        result: The test result.

    Return:
        The metrics string.
    """
    # pylint: disable=unused-argument
    # TODO: Use image to create mtex/s metric
    name = "%5s %s" % (result.blkSz, result.name)
    tPSNR = "%2.5f dB" % result.psnr
    tTTime = "%3.5f s" % result.tTime
    tCTime = "%3.5f s" % result.cTime

    return "%s | %8s | %8s | %8s" % (name, tPSNR, tTTime, tCTime)


def format_result(image, reference, result):
    """
    Format a metrics string for a comparison result.

    Args:
        image: The image being tested.
        reference: The reference result to compare against.
        result: The test result.

    Return:
        The metrics string.
    """
    # pylint: disable=unused-argument
    # TODO: Use image to create mtex/s metric
    dPSNR = result.psnr - reference.psnr
    sTTime = reference.tTime / result.tTime
    sCTime = reference.cTime / result.cTime

    name = "%5s %s" % (result.blkSz, result.name)
    tPSNR = "%2.3f dB (% 1.3f dB)" % (result.psnr, dPSNR)
    tTTime = "%.2f s (%1.1fx)" % (result.tTime, sTTime)
    tCTime = "%.2f s (%1.1fx)" % (result.cTime, sCTime)
    result = determine_result(image, reference, result)

    return "%-32s | %22s | %14s | %14s | %s" % \
           (name, tPSNR, tTTime, tCTime, result.name)


def run_test_set(encoder, testRef, testSet, blockSizes, testRuns):
    """
    Execute all tests in the test set.

    Args:
        encoder: The encoder to use.
        testRef: The test reference results.
        testSet: The test set.
        blockSizes: The block sizes to execute each test against.
        testRuns: The number of test runs.

    Return:
        The result set.
    """
    resultSet = trs.ResultSet(testSet.name)

    curCount = 0
    maxCount = count_test_set(testSet, blockSizes)

    title = "Test Set: %s / Encoder: %s" % (testSet.name, encoder.name)
    print(title)
    print("=" * len(title))

    for blkSz in blockSizes:
        for image in testSet.tests:
            # 3D block sizes require 3D images
            if is_3d(blkSz) != image.is3D:
                continue

            curCount += 1

            dat = (curCount, maxCount, blkSz, image.testFile)
            print("Running %u/%u %s %s ... " % dat, end='', flush=True)
            res = encoder.run_test(image, blkSz, "-thorough", testRuns)
            res = trs.Record(blkSz, image.testFile, res[0], res[1], res[2])
            resultSet.add_record(res)

            if testRef:
                refResult = testRef.get_matching_record(res)
                res.set_status(determine_result(image, refResult, res))
                res = format_result(image, refResult, res)
            else:
                res = format_solo_result(image, res)

            print("\r[%3u] %s" % (curCount, res))

    return resultSet


def get_encoder_params(encoderName, imageSet):
    """
    The the encoder and image set parameters for a test run.

    Args:
        encoderName: the encoder name from the command line.
        imageSet: the test image set.
    """
    if encoderName == "1.7":
        encoder = te.Encoder1x()
        name = "reference-1.7"
        outDir = "Test/Images/%s" % imageSet
        refName = None
    elif encoderName == "prototype":
        encoder = te.EncoderProto()
        name = "reference-prototype"
        outDir = "Test/Images/%s" % imageSet
        refName = None
    elif encoderName == "intelispc":
        encoder = te.EncoderISPC()
        name = "reference-intelispc"
        outDir = "Test/Images/%s" % imageSet
        refName = None
    else:
        encoder = te.Encoder2x(encoderName)
        name = "develop-%s" % encoderName
        outDir = "TestOutput/%s" % imageSet
        refName = "reference-1.7"

    return (encoder, name, outDir, refName)


def parse_command_line():
    """
    Parse the command line.
    """
    parser = argparse.ArgumentParser()

    refcoders = ["1.7", "prototype", "intelispc"]
    testcoders = ["nointrin", "sse2", "sse4.2", "avx2"]
    coders = refcoders + testcoders + ["all"]
    parser.add_argument("--encoder", dest="encoders", default="avx2",
                        choices=coders, help="test encoder variant")

    astcProfile = ["ldr", "ldrs", "hdr", "all"]
    parser.add_argument("--color-profile", dest="profiles", default="all",
                        choices=astcProfile, help="test color profile")

    imgFormat = ["l", "xy", "rgb", "rgba", "all"]
    parser.add_argument("--color-format", dest="formats", default="all",
                        choices=imgFormat, help="test color format")

    choices = list(TEST_BLOCK_SIZES) + ["all"]
    parser.add_argument("--block-size", dest="blockSizes",
                        action="append", choices=choices,
                        help="test block size")

    testDir = os.path.dirname(__file__)
    testDir = os.path.join(testDir, "Images")
    testSets = []
    for path in os.listdir(testDir):
        fqPath = os.path.join(testDir, path)
        if os.path.isdir(fqPath):
            testSets.append(path)
    testSets.append("all")

    parser.add_argument("--test-set", dest="testSets", default="Small",
                        choices=testSets, help="test image test set")

    parser.add_argument("--repeats", dest="testRepeats", default=1,
                        type=int, help="test iteration count")

    args = parser.parse_args()

    # Turn things into canonical format lists
    args.encoders = testcoders if args.encoders == "all" \
        else [args.encoders]

    if not args.blockSizes or ("all" in args.blockSizes):
        args.blockSizes = TEST_BLOCK_SIZES

    args.testSets = testSets[:-1] if args.testSets == "all" \
        else [args.testSets]

    args.profiles = astcProfile[:-1] if args.profiles == "all" \
        else [args.profiles]

    args.formats = imgFormat[:-1] if args.formats == "all" \
        else [args.formats]

    return args


def main():
    """
    The main function.
    """
    # Parse command lines
    args = parse_command_line()

    testSetCount = 0
    worstResult = trs.Result.NOTRUN

    for imageSet in args.testSets:
        for encoderName in args.encoders:
            (encoder, name, outDir, refName) = \
                get_encoder_params(encoderName, imageSet)

            testDir = "Test/Images/%s" % imageSet
            testRes = "%s/astc_%s_results.csv" % (outDir, name)

            testRef = None
            if refName:
                testRefPath = "%s/astc_%s_results.csv" % (testDir, refName)
                testRef = trs.ResultSet(imageSet)
                testRef.load_from_file(testRefPath)

            testSetCount += 1
            testSet = tts.TestSet(imageSet, testDir,
                                  args.profiles, args.formats)

            resultSet = run_test_set(encoder, testRef, testSet,
                                     args.blockSizes, args.testRepeats)

            resultSet.save_to_file(testRes)

            if refName:
                summary = resultSet.get_results_summary()
                worstResult = max(summary.get_worst_result(), worstResult)
                print(summary)

    if (testSetCount > 1) and (worstResult != trs.Result.NOTRUN):
        print("OVERALL STATUS: %s" % worstResult.name)

    if worstResult == trs.Result.FAIL:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
