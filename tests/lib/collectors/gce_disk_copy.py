#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tests for the GCEDiskCopy collector."""


import unittest

from googleapiclient.errors import HttpError
import httplib2

import mock
from libcloudforensics.providers.gcp.internal import project as gcp_project
from libcloudforensics.providers.gcp.internal import compute
from libcloudforensics import errors as lcf_errors

from dftimewolf.lib import errors
from dftimewolf.lib.containers import containers
from dftimewolf.lib.collectors import gce_disk_copy
from tests.lib import modules_test_base


FAKE_PROJECT = gcp_project.GoogleCloudProject(
    'test-target-project-name',
    'fake_zone')
FAKE_INSTANCE = compute.GoogleComputeInstance(
    FAKE_PROJECT.project_id,
    'fake_zone',
    'fake-instance')
FAKE_DISK = compute.GoogleComputeDisk(
    FAKE_PROJECT.project_id,
    'fake_zone',
    'disk1')
FAKE_DISK_MULTIPLE = [
    compute.GoogleComputeDisk(
        FAKE_PROJECT.project_id,
        'fake_zone',
        'disk1'),
    compute.GoogleComputeDisk(
        FAKE_PROJECT.project_id,
        'fake_zone',
        'disk2')
]
FAKE_BOOT_DISK = compute.GoogleComputeDisk(
    FAKE_PROJECT.project_id,
    'fake_zone',
    'bootdisk')
FAKE_DISK_COPY = [
    compute.GoogleComputeDisk(
        FAKE_PROJECT.project_id,
        'fake_zone',
        'disk1-copy'),
    compute.GoogleComputeDisk(
        FAKE_PROJECT.project_id,
        'fake_zone',
        'disk2-copy')
]

class GCEDiskCopyTest(modules_test_base.ModuleTestBase):
  """Tests for the GCEDiskCopy collector."""

  # For pytype
  _module: gce_disk_copy.GCEDiskCopy

  def setUp(self):
    self._InitModule(gce_disk_copy.GCEDiskCopy)
    super().setUp()

  def testSetUp(self):
    """Tests the SetUp method of the collector."""
    # Test setup with single disk and instance
    self._module.SetUp(
        'test-destination-project-name',
        'test-source-project-name',
        'fake_zone',
        remote_instance_names='my-owned-instance',
        disk_names='fake-disk',
        all_disks=True,
        stop_instances=True
    )
    self.assertEqual(self._module.destination_project.project_id,
                     'test-destination-project-name')
    self.assertEqual(self._module.source_project.project_id,
                     'test-source-project-name')
    self.assertEqual(self._module.remote_instance_names, ['my-owned-instance'])
    self.assertEqual(self._module.disk_names, ['fake-disk'])
    self.assertEqual(self._module.all_disks, True)
    self.assertEqual(self._module.stop_instances, True)

    # Test setup with multiple disks and instances
    self._module.SetUp(
        'test-destination-project-name',
        'test-source-project-name',
        'fake_zone',
        'my-owned-instance1,my-owned-instance2',
        'fake-disk-1,fake-disk-2',
        False,
        False
    )
    self.assertEqual(self._module.destination_project.project_id,
                     'test-destination-project-name')
    self.assertEqual(self._module.source_project.project_id,
                     'test-source-project-name')
    self.assertEqual(sorted(self._module.remote_instance_names), sorted([
                     'my-owned-instance1', 'my-owned-instance2']))
    self.assertEqual(sorted(self._module.disk_names), sorted([
                     'fake-disk-1', 'fake-disk-2']))
    self.assertEqual(self._module.all_disks, False)
    self.assertEqual(self._module.stop_instances, False)

    # Test setup with no destination project
    self._module.SetUp(
        None,
        'test-source-project-name',
        'fake_zone',
        remote_instance_names='my-owned-instance',
        disk_names='fake-disk',
        all_disks=True,
        stop_instances=True
    )
    self.assertEqual(self._module.destination_project.project_id,
                     'test-source-project-name')
    self.assertEqual(self._module.source_project.project_id,
                     'test-source-project-name')
    self.assertEqual(self._module.remote_instance_names, ['my-owned-instance'])
    self.assertEqual(self._module.disk_names, ['fake-disk'])
    self.assertEqual(self._module.all_disks, True)
    self.assertEqual(self._module.stop_instances, True)

  def testSetUpNothingProvided(self):
    """Tests that SetUp fails if no disks or instances are provided."""
    with self.assertRaises(errors.DFTimewolfError) as error:
      self._module.SetUp(
          'test-destination-project-name',
          'test-source-project-name',
          'fake_zone',
          None,
          None,
          False,
          False
      )
    self.assertEqual(error.exception.message,
        'You need to specify at least an instance name or disks to copy')

  def testStopWithNoInstance(self):
    """Tests that SetUp fails if stop instance is requested, but no instance
    provided.
    """
    with self.assertRaises(errors.DFTimewolfError) as error:
      self._module.SetUp(
          'test-destination-project-name',
          'test-source-project-name',
          'fake_zone',
          None,
          'disk1',
          False,
          True
      )
    self.assertEqual(error.exception.message,
        'You need to specify an instance name to stop the instance')

  # pylint: disable=line-too-long,invalid-name
  @mock.patch('libcloudforensics.providers.gcp.internal.compute.GoogleComputeInstance.GetBootDisk')
  @mock.patch('libcloudforensics.providers.gcp.internal.compute.GoogleCloudCompute.GetDisk')
  @mock.patch('libcloudforensics.providers.gcp.internal.compute.GoogleComputeInstance.ListDisks')
  @mock.patch('libcloudforensics.providers.gcp.internal.compute.GoogleCloudCompute.GetInstance')
  # We're manually calling protected functions
  # pylint: disable=protected-access
  def testPreProcess(self,
                     mock_get_instance,
                     mock_list_disks,
                     mock_get_disk,
                     mock_GetBootDisk):
    """Tests the _FindDisksToCopy function with different SetUp() calls."""
    mock_list_disks.return_value = {
        'bootdisk': FAKE_BOOT_DISK,
        'disk1': FAKE_DISK
    }
    mock_get_disk.return_value = FAKE_DISK
    mock_get_instance.return_value = FAKE_INSTANCE
    mock_GetBootDisk.return_value = FAKE_BOOT_DISK

    # Nothing is specified, GoogleCloudCollector should collect the instance's
    # boot disk
    self._module.SetUp(
        'test-analysis-project-name',
        'test-target-project-name',
        'fake_zone',
        'my-owned-instance',
        None,
        False,
        False
    )
    self._module.PreProcess()
    disks = self._module.GetContainers(containers.GCEDisk)
    self.assertEqual(len(disks), 1)
    self.assertEqual(disks[0].name, 'bootdisk')
    mock_GetBootDisk.assert_called_once()

    # Specifying all_disks should return all disks for the instance
    # (see mock_list_disks return value)
    self._module.GetContainers(containers.GCEDisk, True)  # Clear containers first
    self._module.SetUp(
        'test-analysis-project-name',
        'test-target-project-name',
        'fake_zone',
        'my-owned-instance',
        None,
        True,
        False
    )
    self._module.PreProcess()
    disks = self._module.GetContainers(containers.GCEDisk)
    self.assertEqual(len(disks), 2)
    self.assertEqual(disks[0].name, 'bootdisk')
    self.assertEqual(disks[1].name, 'disk1')

    # Specifying a csv list of disks should have those included also
    self._module.GetContainers(containers.GCEDisk, True)  # Clear containers first
    self._module.SetUp(
        'test-analysis-project-name',
        'test-target-project-name',
        'fake_zone',
        'my-owned-instance',
        'another_disk_1,another_disk_2',
        True,
        False
    )
    self._module.PreProcess()
    disks = self._module.GetContainers(containers.GCEDisk)
    self.assertEqual(len(disks), 4)

    expected = sorted(['another_disk_1', 'another_disk_2', 'bootdisk', 'disk1'])
    actual = sorted([d.name for d in disks])
    self.assertEqual(expected, actual)

  @mock.patch('libcloudforensics.providers.gcp.internal.compute.GoogleCloudCompute.GetInstance')
  def testInstanceNotFound(self, mock_GetInstance):
    """Test that an error is thrown when the instance isn't found."""
    mock_GetInstance.side_effect = lcf_errors.ResourceNotFoundError('message',
                                                                    'name')

    self._module.SetUp(
        'test-analysis-project-name',
        'test-target-project-name',
        'fake_zone',
        'nonexistent',
        None,
        False,
        False
    )
    with self.assertRaises(errors.DFTimewolfError) as error:
      self._module.PreProcess()

    self.assertEqual(
        error.exception.message, 'No instances found with disks to copy.')

  @mock.patch('libcloudforensics.providers.gcp.internal.compute.GoogleCloudCompute.GetInstance')
  def testHTTPErrors(self, mock_GetInstance):
    """Tests the 403 checked for in PreProcess."""
    # 403
    mock_GetInstance.side_effect = HttpError(httplib2.Response({
        'status': 403,
        'reason': 'The caller does not have permission'
    }), b'')

    self._module.SetUp(
        'test-analysis-project-name',
        'test-target-project-name',
        'fake_zone',
        'nonexistent',
        None,
        False,
        False
    )
    with self.assertRaises(errors.DFTimewolfError) as error:
      self._module.PreProcess()
    self.assertEqual(error.exception.message,
        '403 response. Do you have appropriate permissions on the project?')

    # Other (500)
    mock_GetInstance.side_effect = HttpError(httplib2.Response({
        'status': 500,
        'reason': 'Internal Server Error'
    }), b'')

    self._module.SetUp(
        'test-analysis-project-name',
        'test-target-project-name',
        'fake_zone',
        'nonexistent',
        None,
        False,
        False
    )
    with self.assertRaises(errors.DFTimewolfError) as error:
      self._module.PreProcess()
    self.assertEqual(error.exception.message,
        '<HttpError 500 "Ok">')

  # pylint: disable=line-too-long
  @mock.patch('libcloudforensics.providers.gcp.internal.compute.GoogleCloudCompute.GetInstance')
  @mock.patch('libcloudforensics.providers.gcp.forensics.CreateDiskCopy')
  @mock.patch('dftimewolf.lib.collectors.gce_disk_copy.GCEDiskCopy._GetDisksFromInstance')
  @mock.patch('libcloudforensics.providers.gcp.internal.compute.GoogleComputeInstance.ListDisks')
  def testProcessWithStop(self,
                          mock_list_disks,
                          mock_getDisksFromInstance,
                          mock_CreateDiskCopy,
                          mock_GetInstance):
    """Tests the collector's Process() function, stopping the instance."""
    mock_getDisksFromInstance.return_value = [
        d.name for d in FAKE_DISK_MULTIPLE]
    mock_CreateDiskCopy.side_effect = FAKE_DISK_COPY
    mock_GetInstance.return_value = FAKE_INSTANCE
    mock_list_disks.return_value = {
        'bootdisk': FAKE_BOOT_DISK,
        'disk1': FAKE_DISK
    }

    self._module.SetUp(
        'test-analysis-project-name',
        'test-target-project-name',
        'fake_zone',
        'my-owned-instance',
        None,
        True,
        True
    )
    FAKE_INSTANCE.Stop = mock.MagicMock()

    self._ProcessModule()

    mock_CreateDiskCopy.assert_has_calls([
        mock.call('test-target-project-name',
                  'test-analysis-project-name',
                  'fake_zone',
                  disk_name='disk1'),
        mock.call('test-target-project-name',
                  'test-analysis-project-name',
                  'fake_zone',
                  disk_name='disk2')])

    FAKE_INSTANCE.Stop.assert_called_once()

    out_disks = [d for d in self._module.GetContainers(containers.GCEDisk)
                 if d.name not in ('disk1', 'disk2')]
    out_disk_names = [d.name for d in out_disks]
    self.assertLen(out_disk_names, 2)
    expected_disk_names = ['disk1-copy', 'disk2-copy']
    self.assertListEqual(out_disk_names, expected_disk_names)
    for d in out_disks:
      self.assertEqual(d.project, 'test-analysis-project-name')

  # pylint: disable=line-too-long
  @mock.patch('libcloudforensics.providers.gcp.internal.compute.GoogleCloudCompute.GetInstance')
  @mock.patch('libcloudforensics.providers.gcp.forensics.CreateDiskCopy')
  @mock.patch('dftimewolf.lib.collectors.gce_disk_copy.GCEDiskCopy._GetDisksFromInstance')
  @mock.patch('libcloudforensics.providers.gcp.internal.compute.GoogleComputeInstance.ListDisks')
  def testProcessWithoutStop(self,
                             mock_list_disks,
                             mock_getDisksFromInstance,
                             mock_CreateDiskCopy,
                             mock_GetInstance):
    """Tests the collector's Process() function."""
    mock_getDisksFromInstance.return_value = [
        d.name for d in FAKE_DISK_MULTIPLE]
    mock_CreateDiskCopy.side_effect = FAKE_DISK_COPY
    mock_GetInstance.return_value = FAKE_INSTANCE
    mock_list_disks.return_value = {
        'bootdisk': FAKE_BOOT_DISK,
        'disk1': FAKE_DISK
    }

    self._module.SetUp(
        'test-analysis-project-name',
        'test-target-project-name',
        'fake_zone',
        'my-owned-instance',
        None,
        True,
        False,
    )
    FAKE_INSTANCE.Stop = mock.MagicMock()

    self._ProcessModule()

    mock_CreateDiskCopy.assert_has_calls([
        mock.call('test-target-project-name',
                  'test-analysis-project-name',
                  'fake_zone',
                  disk_name='disk1'),
        mock.call('test-target-project-name',
                  'test-analysis-project-name',
                  'fake_zone',
                  disk_name='disk2')])

    FAKE_INSTANCE.Stop.assert_not_called()

    out_disks = [d for d in self._module.GetContainers(containers.GCEDisk)
                 if d.name not in ('disk1', 'disk2')]
    out_disk_names = [d.name for d in out_disks]
    self.assertLen(out_disk_names, 2)
    expected_disk_names = ['disk1-copy', 'disk2-copy']
    self.assertListEqual(out_disk_names, expected_disk_names)
    for d in out_disks:
      self.assertEqual(d.project, 'test-analysis-project-name')

  @mock.patch('libcloudforensics.providers.gcp.forensics.CreateDiskCopy')
  def testProcessDiskCopyErrors(self, mock_CreateDiskCopy):
    """Tests that Process errors correctly in some scenarios."""
    # Fail if the disk cannot be found.
    mock_CreateDiskCopy.side_effect = lcf_errors.ResourceNotFoundError(
        'Could not find disk "nonexistent": Disk nonexistent was not found in '
        'project test-source-project-name',
        'name')

    self._module.SetUp(
        'test-destination-project-name',
        'test-source-project-name',
        'fake_zone',
        None,
        'nonexistent',
        False,
        False
    )
    self._module.PreProcess()
    conts = self._module.GetContainers(self._module.GetThreadOnContainerType())
    for d in conts:
      self._module.Process(d)  # pytype: disable=wrong-arg-types
      # GetContainers returns the abstract base class type, but process is
      # called with the instantiated child class.
    with self.assertRaises(errors.DFTimewolfError) as error:
      self._module.PostProcess()
    self.assertEqual(error.exception.message,
        'No successful disk copy operations completed.')

    # Fail if the disk cannot be created
    mock_CreateDiskCopy.side_effect = lcf_errors.ResourceCreationError(
        'Could not create disk. Permission denied.',
        'name')

    self._module.SetUp(
        'test-destination-project-name',
        'test-source-project-name',
        'fake_zone',
        None,
        'nonexistent',
        False,
        False
    )
    self._module.PreProcess()
    conts = self._module.GetContainers(self._module.GetThreadOnContainerType())
    with self.assertRaises(errors.DFTimewolfError) as error:
      for d in conts:
        self._module.Process(d)  # pytype: disable=wrong-arg-types
        # GetContainers returns the abstract base class type, but process is
        # called with the instantiated child class.
    self.assertEqual(error.exception.message,
        'Could not create disk. Permission denied.')

  @mock.patch('libcloudforensics.providers.gcp.internal.compute.GoogleCloudCompute.GetInstance')
  @mock.patch('libcloudforensics.providers.gcp.forensics.CreateDiskCopy')
  @mock.patch('dftimewolf.lib.collectors.gce_disk_copy.GCEDiskCopy._GetDisksFromInstance')
  @mock.patch('libcloudforensics.providers.gcp.internal.compute.GoogleComputeInstance.ListDisks')
  def testProcessMultipleSingleFailure(self,
                                       mock_list_disks,
                                       mock_getDisksFromInstance,
                                       mock_CreateDiskCopy,
                                       mock_GetInstance):
    """Tests processing when multiple instances are requested, but one is not found."""
    mock_getDisksFromInstance.side_effect = [
        lcf_errors.ResourceNotFoundError('Not found', 'Not found'),
        [d.name for d in FAKE_DISK_MULTIPLE]]
    mock_CreateDiskCopy.side_effect = FAKE_DISK_COPY
    mock_GetInstance.return_value = FAKE_INSTANCE
    mock_list_disks.return_value = {
        'bootdisk': FAKE_BOOT_DISK,
        'disk1': FAKE_DISK
    }

    self._module.SetUp(
        destination_project_name='test-analysis-project-name',
        source_project_name='test-target-project-name',
        destination_zone='fake_zone',
        remote_instance_names='not-found,found',
        disk_names=None,
        all_disks=True,
        stop_instances=False,
    )
    with mock.patch.object(
        self._module, 'PublishMessage') as mock_publishmessage:
      self._ProcessModule()

    mock_publishmessage.assert_has_calls(
        [mock.call('Instance "not-found" in test-target-project-name not found '
        'or insufficient permissions', is_error=True),
         mock.call('Disk disk1 successfully copied to disk1-copy'),
         mock.call('Disk disk2 successfully copied to disk2-copy')],
        any_order=True)

    mock_CreateDiskCopy.assert_has_calls([
        mock.call('test-target-project-name',
                  'test-analysis-project-name',
                  'fake_zone',
                  disk_name='disk1'),
        mock.call('test-target-project-name',
                  'test-analysis-project-name',
                  'fake_zone',
                  disk_name='disk2')])

    out_disks = [d for d in self._module.GetContainers(containers.GCEDisk)
                 if d.name not in ('disk1', 'disk2')]
    out_disk_names = [d.name for d in out_disks]
    self.assertLen(out_disk_names, 2)
    expected_disk_names = ['disk1-copy', 'disk2-copy']
    self.assertListEqual(out_disk_names, expected_disk_names)
    for d in out_disks:
      self.assertEqual(d.project, 'test-analysis-project-name')


if __name__ == '__main__':
  unittest.main()
