class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/02/2d/d7b47a75d89f362dd8baf0ec4bc456a717d8e3d1596441c4ccb7b307318b/myplaylist-0.2.0-py3-none-any.whl",
      using: :nounzip
  sha256 "283bb1d0f6ddefeb0ba79a26065335f9aeb4a54be6ef1d61c7296f697df602d7"
  license "MIT"

  depends_on "python@3.11"
  depends_on "mpv"

  def install
    venv = libexec/"venv"
    system Formula["python@3.11"].opt_bin/"python3.11", "-m", "venv", venv
    system venv/"bin/pip", "install", "myplaylist==#{version}"
    bin.install_symlink venv/"bin/myplaylist"
  end

  test do
    assert_match "myplaylist", shell_output("#{bin}/myplaylist --help")
  end
end
