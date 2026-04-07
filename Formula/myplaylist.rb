class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/f5/da/579cdd42ae8d434b4088826f92f98281ce3aea59cdbe8929d07d9a795c8b/myplaylist-0.3.5-py3-none-any.whl",,,,,,,
      using: :nounzip
  sha256 "28a8d61cbf6ad8e245befea247fe7c930e5193c8229368ccfb5467c04725a5c6"
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
