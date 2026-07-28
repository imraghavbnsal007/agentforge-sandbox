/** Repository discovery — the github_app-mode replacement for pasting a URL. */

export interface Repository {
  github_repository_id: number;
  owner: string;
  name: string;
  full_name: string;
  default_branch: string;
  private: boolean;
  archived: boolean;
  disabled: boolean;
  /** False when archived or disabled — cannot receive pull requests. */
  is_usable: boolean;
  last_synced_at: string | null;
  installation_id: number;
  installation_account: string;
  installation_active: boolean;
  is_registered: boolean;
  project_id: number | null;
}

export interface RepositoryList {
  app_configured: boolean;
  install_url: string | null;
  /** False when the user has no installations at all — show "install the App"
   *  rather than "no repositories found". */
  has_installations: boolean;
  repositories: Repository[];
}

export const EMPTY_REPOSITORY_LIST: RepositoryList = {
  app_configured: false,
  install_url: null,
  has_installations: false,
  repositories: [],
};
