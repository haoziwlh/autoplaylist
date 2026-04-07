class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/6a/23/119930031db2f39d52c573c8f0c56f6b5a08fe3e781ef52801f9c6a10379/myplaylist-0.3.9-py3-none-any.whl",,,,,,,,,,,
      using: :nounzip
  sha256 "146ae9bcdf53419c56ae76f5437fa7e83609fd72796b3e00335055933d28c342"
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
