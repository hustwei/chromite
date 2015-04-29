# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Install/copy the image to the device."""

from __future__ import print_function

from chromite.cli import command
from chromite.cli import flash
from chromite.lib import commandline
from chromite.lib import cros_logging as logging
from chromite.lib import dev_server_wrapper


@command.CommandDecorator('flash')
class FlashCommand(command.CliCommand):
  """Update the device with an image.

  This command updates the device with the image
  (ssh://<hostname>:{port}, copies an image to a removable device
  (usb://<device_path), or copies a xbuddy path to a local
  file path with (file://file_path).

  For device update, it assumes that device is able to accept ssh
  connections.

  For rootfs partition update, this command may launch a devserver to
  generate payloads. As a side effect, it may create symlinks in
  static_dir/others used by the devserver.
  """

  EPILOG = """
To update/image the device with the latest locally built image:
  cros flash device latest
  cros flash device

To update/image the device with an xbuddy path:
  cros flash device xbuddy://{local, remote}/<board>/<version>

  Common xbuddy version aliases are 'latest' (alias for 'latest-stable')
  latest-{dev, beta, stable, canary}, and latest-official.

To update/image the device with a local image path:
  cros flash device /path/to/image.bin

Examples:
  cros flash 192.168.1.7 xbuddy://remote/x86-mario/latest-canary
  cros flash 192.168.1.7 xbuddy://remote/x86-mario-paladin/R32-4830.0.0-rc1
  cros flash usb:// xbuddy://remote/trybot-x86-mario-paladin/R32-5189.0.0-b100
  cros flash usb:///dev/sde xbuddy://peppy/latest
  cros flash file:///~/images xbuddy://peppy/latest

  For more information and known problems/fixes, please see:
  http://dev.chromium.org/chromium-os/build/cros-flash
"""

  # Override base class property to enable stats upload.
  upload_stats = True

  @classmethod
  def AddParser(cls, parser):
    """Add parser arguments."""
    super(FlashCommand, cls).AddParser(parser)
    cls.AddDeviceArgument(parser, schemes=[commandline.DEVICE_SCHEME_FILE,
                                           commandline.DEVICE_SCHEME_SSH,
                                           commandline.DEVICE_SCHEME_USB])
    parser.add_argument(
        'image', nargs='?', default='latest', help="A local path or an xbuddy "
        "path: xbuddy://{local|remote}/board/version/{image_type} image_type "
        "can be: 'test', 'dev', 'base', or 'recovery'. Note any strings that "
        "do not map to a real file path will be converted to an xbuddy path "
        "i.e., latest, will map to xbuddy://latest.")
    parser.add_argument(
        '--clear-cache', default=False, action='store_true',
        help='Clear the devserver static directory. This deletes all the '
        'downloaded images and payloads, and also payloads generated by '
        'the devserver. Default is not to clear.')

    update = parser.add_argument_group('Advanced device update options')
    update.add_argument(
        '--board', help='The board to use. By default it is '
        'automatically detected. You can override the detected board with '
        'this option')
    update.add_argument('--brick', help='The brick to use.')
    update.add_argument(
        '--yes', default=False, action='store_true',
        help='Answer yes to any prompt. Use with caution.')
    update.add_argument(
        '--force', action='store_true',
        help='Ignore sanity checks, just do it. Implies --yes.')
    update.add_argument(
        '--no-reboot', action='store_false', dest='reboot', default=True,
        help='Do not reboot after update. Default is always reboot.')
    update.add_argument(
        '--no-wipe', action='store_false', dest='wipe', default=True,
        help='Do not wipe the temporary working directory. Default '
        'is always wipe.')
    update.add_argument(
        '--no-stateful-update', action='store_false', dest='stateful_update',
        help='Do not update the stateful partition on the device. '
        'Default is always update.')
    update.add_argument(
        '--no-rootfs-update', action='store_false', dest='rootfs_update',
        help='Do not update the rootfs partition on the device. '
        'Default is always update.')
    update.add_argument(
        '--src-image-to-delta', type='path',
        help='Local path to an image to be used as the base to generate '
        'delta payloads.')
    update.add_argument(
        '--clobber-stateful', action='store_true', default=False,
        help='Clobber stateful partition when performing update.')
    update.add_argument(
        '--no-ping', dest='ping', action='store_false', default=True,
        help='Do not ping the device before attempting to connect to it.')
    update.add_argument(
        '--disable-rootfs-verification', default=False, action='store_true',
        help='Disable rootfs verification after update is completed.')
    update.add_argument(
        '--project-sdk', nargs='?', const='', metavar='VERSION',
        help='Install a Project SDK image. This resets the device to a clean '
        'state and ensures that it is compatible with the development '
        'environment. The image argument is ignored. If no version provided, '
        'will use the current SDK version.')

    usb = parser.add_argument_group('USB specific options')
    usb.add_argument(
        '--install', default=False, action='store_true',
        help='Install to the USB device using the base disk layout.')

  def _HandleException(self, exception):
    """Perform common logging and cleanup for exceptions."""
    logging.error(exception)
    logging.error('cros flash failed before completing.')
    if self.options.debug:
      raise exception
    else:
      raise SystemExit(1)

  def Run(self):
    """Perfrom the cros flash command."""
    self.options.Freeze()
    try:
      flash.Flash(
          self.options.device,
          self.options.image,
          project_sdk_image=self.options.project_sdk is not None,
          sdk_version=self.options.project_sdk or None,
          board=self.options.board,
          brick_name=self.options.brick or self.curr_brick_locator,
          install=self.options.install,
          src_image_to_delta=self.options.src_image_to_delta,
          rootfs_update=self.options.rootfs_update,
          stateful_update=self.options.stateful_update,
          clobber_stateful=self.options.clobber_stateful,
          reboot=self.options.reboot,
          wipe=self.options.wipe,
          ping=self.options.ping,
          disable_rootfs_verification=self.options.disable_rootfs_verification,
          clear_cache=self.options.clear_cache,
          yes=self.options.yes,
          force=self.options.force,
          debug=self.options.debug)
    except dev_server_wrapper.ImagePathError as e:
      logging.error('To get the latest remote image, please run:\n'
                    'cros flash --board=%s %s remote/latest',
                    self.options.board, self.options.device.raw)
      self._HandleException(e)
    except Exception as e:
      self._HandleException(e)
    else:
      logging.info('cros flash completed successfully.')
