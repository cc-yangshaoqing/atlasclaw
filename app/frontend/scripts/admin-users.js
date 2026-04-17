/*
 *  Copyright 2021  Qianyun, Inc. All rights reserved.
 */

const TARGET_PATH = '/admin/users'

if (window.location.pathname !== TARGET_PATH) {
  window.location.replace(TARGET_PATH)
}
