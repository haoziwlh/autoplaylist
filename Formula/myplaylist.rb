class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/b1/29/f4a13f44829cfc3c5dd06357c750baa734a929cbc47a83964b9da151134b/myplaylist-0.3.1-py3-none-any.whl",,,
      using: :nounzip
  sha256 "f14db44d1e6936034e49691646b2ee02abfe88ba8f10944ba009f32ce52d1ae9"
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
