class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/f8/ae/6e60aed764e4652268f6f5bed71098c8a39c6e743d78a42a8fac96e3a63a/myplaylist-0.4.4-py3-none-any.whl",,,,,,,,,,,,,,,,,,,,,,,,,,
      using: :nounzip
  sha256 "e3e35e672c2b11201229212fe896f9dbdf1531637c82b476f1f8344d18b6ef0d"
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
