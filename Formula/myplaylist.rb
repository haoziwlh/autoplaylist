class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/b5/2f/0d1db410a86183b2be1797af3e96016e6f02e47f550cfad1259939b4de1e/myplaylist-0.3.11-py3-none-any.whl",,,,,,,,,,,,
      using: :nounzip
  sha256 "05c5def732e2b1f71437f8d841c585161fc37e68e8071e225d70fbed2be7db77"
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
